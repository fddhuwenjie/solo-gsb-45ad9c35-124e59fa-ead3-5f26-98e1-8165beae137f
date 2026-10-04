# 低空航线空域时窗审查台

用 **Python Flask + SQLite + 原生 JavaScript/SVG** 实现的本地审查工具：在画布上录入带**高度层、速度、起降时刻**的航点航段，维护带**生效区间**的禁飞多边形；系统把航段按走廊半宽展开为带时间的**扫掠走廊**，计算与禁飞区的三维冲突（**平面相交 ∩ 高度层重叠 ∩ 时间窗重叠**），给出**首个冲突区间**和**见证位置**；支持拖动航点/禁飞区顶点后自动重算，可保存/载入命名版本，并能从命名版本**发布航线**：取版本航线配上当前工作区禁飞区重新审查，通过后固化为不可改写的递增发布号记录。

## 一条命令启动

```bash
docker compose up --build
```

启动后浏览器访问：

> **http://localhost:8000**

（容器内 gunicorn 监听 `0.0.0.0:8000`，SQLite 数据文件持久化在 Docker 卷 `airspace-data` 中的 `/data/console.db`。）

不用 Docker 时：

```bash
pip install -r requirements.txt
python app.py          # 同样监听 http://localhost:8000
```

## 模型与判定口径

画布为**局部平面坐标系**（高度 m；速度 km/h；时间本地时区）。坐标单位不预设，通过侧栏「画布比例（单位/km）」声明 **1 km 对应多少画布单位**（默认 100，即画布单位视为 10 m），航段长度据此换算。

### 航线
- 有序航点 `(x, y, 高度)`；相邻航点构成航段。
- 每段独立速度（km/h），由 `起飞时刻 + Σ 航段长度/速度` 逐点推出 ETA（航点预达时刻），长度 = 画布距离 ÷ 画布比例。
- 航段折线按「走廊半宽（km）」做 round-cap/round-join 缓冲（`shapely.buffer`），即扫掠走廊平面范围；画布上以同宽描边近似可视化。

### 禁飞区
- 多边形顶点（画布上绘制或表单维护）。
- 高度层 `[minAlt, maxAlt]`（m）。
- 生效时窗 `[startTime, endTime]`，端点可空表示不限。
- 可勾选启用/停用。

### 三维 + 时间冲突
对每条航段与每个禁飞区：

1. **平面（按连通部件分别计算，不合并）**：走廊缓冲多边形 ∩ 禁飞多边形；相交结果可能是 `MultiPolygon / MultiLineString / MultiPoint / GeometryCollection`，系统先递归展平为**各自独立的连通部件**，再把每个部件分别投影到航段方向，得到一组相互独立的航段参数区间 `f∈[0,1]`。航段先穿多边形一侧、再穿另一侧（如凹形禁飞区）时，两段区间**中间的空隙保留为空隙**，不会被外包区间 `[f_min, f_max]` 填平。
2. **高度（逐部件求交）**：航段高度在 `a0→a1` 间线性变化，先求出落在禁飞高度层 `[minAlt,maxAlt]` 的 `f` 子区间（解析端点裁剪），再**分别**与每个平面部件区间求交。
3. **时间（逐段映射、逐段截短）**：把每个子区间独立映射为绝对时刻区间，再与禁飞生效窗求交；空窗端点视为 ±∞。区间被时窗截短后，按**实际进入/退出时刻反推最终的 `f`**，因此 `enterFrac/exitFrac` 与 `enterTime/exitTime` 始终对应同一段最终冲突。
4. 三者按**闭区间实际重叠**判定，非空即冲突：平面上的线接触（走廊边界擦过多边形边）、点接触（擦过顶点/圆端帽尖点），以及时刻区间端点恰好落在生效窗沿，都算命中。平面区间退化为点、或被时窗夹成点时报告为瞬时擦碰（`instant: true`）。

每条结果的 `enterFrac、exitFrac、enterTime、exitTime、altLow/altHigh、witness` 都取自**同一段最终冲突**；时窗截短区间时，见证点随实际进入时刻移动到被截短区间的进入端中心线位置。多部件相交会输出多条互不合并的结果，结果按实际进入时刻排序，**首个冲突取最早进入的一段**，画布以红色★标出。

> 注意：走廊缓冲采用 round 端帽，航段衔接处为圆弧过渡；冲突线段在画布上沿中心线绘制，宽度等于走廊宽，仅供定位参考，**计算以 shapely 的真实缓冲区相交为准**。


## 操作说明

| 操作 | 方式 |
|---|---|
| 平移 / 缩放 | 拖动空白处平移；滚轮以光标为中心缩放 |
| 追加航点 | 工具栏「＋ 航点」→ 单击画布；侧栏可改名称/坐标/高度 |
| 航段速度 | 侧栏航点卡片之间的航段行（km/h），ETA 自动刷新 |
| 画禁飞区 | 「✎ 绘制禁飞区」→ 单击落点，**双击或回车**完成；Esc 取消 |
| 编辑禁飞区 | 点选多边形后，画布上拖动黄色顶点，侧栏改高度/时窗/名称 |
| 重算 | 任何编辑后自动重算（约 350ms 防抖），也可点「重新审查」 |
| 保存版本 | 顶部输入版本名（可空，自动用时间戳）→「💾 保存版本」；侧栏可载入/删除 |
| 发布航线 | 侧栏版本列表点「发布」：该版本航线 + 当前工作区禁飞区重新审查，通过后固化递增发布号；「发布航线」区查看发布号、来源版本与审查结果（点「详情」看快照） |

首次启动会写入一条演示数据（4 个航点、3 个禁飞区，含平面+高度+时窗命中、高度不命中、时窗不命中三种样例）。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 当前工作状态 |
| PUT | `/api/state` | 保存工作状态（编辑时自动防抖落库；工作区修订号 +1） |
| POST | `/api/analyze` | 提交状态，返回航段时刻、错误、全部冲突条目、首个冲突 |
| GET | `/api/versions` | 版本列表 |
| POST | `/api/versions` | 保存命名版本 `{name, state}` |
| GET/DELETE | `/api/versions/<id>` | 取出版本快照 / 删除 |
| GET | `/api/releases` | 当前工作区修订号、已发布号与发布记录摘要 |
| POST | `/api/releases` | 发布 `{versionId, workspaceRev, publishedRev}`；失败返回原因（冲突附明细），原发布不变 |
| GET | `/api/releases/<no>` | 某次发布的完整快照（组合状态 + 审查结果），永不改写 |

### 发布航线

把某个**命名版本的航线**与**当前工作区的禁飞区**组合重新审查，审查通过（无错误、无冲突）后在**单个事务**里原子固化一条发布记录：

- 发布号从 1 起单调递增；记录包含发布号、来源版本 ID/名称、组合状态快照与完整审查结果。
- 乐观并发：发布请求需带上读取时的 `workspaceRev`（工作区修订号，每次保存工作区 +1）与 `publishedRev`（当前已发布号）；任一已变化则返回 `409` 与原因（`workspace_changed` / `published_changed`，附当前号）。
- 其余拒绝情形：版本已删除（`404 version_deleted`）、航线没有非零长度航段（`422 no_live_segment`）、审查有错误或冲突（`422 review_failed`，响应附 `errors` / `entries` 冲突明细与 `first`）。所有失败都整体回滚，**原发布不变**。
- 发布记录只增不改：之后编辑工作区、保存新版本或**删除来源版本**，都不会改写已发布内容。

### 发布 API 调用示例（curl，端口 8000）

服务启动后（`docker compose up --build` 或 `python app.py`，均为 **http://localhost:8000**）依次执行：

```bash
# ① 保存一个命名版本（航线：A→B 一段，200m 等高，速度 24km/h）
curl -s -X POST http://localhost:8000/api/versions \
  -H 'Content-Type: application/json' \
  -d '{"name":"发布候选-东线","state":{"route":{"departureTime":"2026-10-01T08:00","unitScale":100,"corridorHalfWidth":0.3,"speeds":[24],"waypoints":[{"id":"w1","name":"A","x":100,"y":100,"alt":200},{"id":"w2","name":"B","x":500,"y":100,"alt":200}]},"nfzs":[]}}'
# → {"ok":true,"id":1,"name":"发布候选-东线",...}

# ② 工作区放一个远离航线的禁飞区（与页面自动保存同一接口）
curl -s -X PUT http://localhost:8000/api/state \
  -H 'Content-Type: application/json' \
  -d '{"route":{"departureTime":"2026-10-01T08:00","unitScale":100,"corridorHalfWidth":0.3,"speeds":[24],"waypoints":[{"id":"w1","name":"A","x":100,"y":100,"alt":200},{"id":"w2","name":"B","x":500,"y":100,"alt":200}]},"nfzs":[{"id":"n1","name":"南侧限制区","vertices":[[100,500],[300,500],[300,600],[100,600]],"minAlt":0,"maxAlt":400,"startTime":"","endTime":"","enabled":true}]}'
# → {"ok":true}

# ③ 读取当前工作区修订号与已发布号
curl -s http://localhost:8000/api/releases
# → {"workspaceRev":1,"publishedRev":0,"releases":[]}

# ④ 发起发布：版本 1 的航线 + 当前工作区禁飞区（③ 读到的两个号原样带上）
curl -s -X POST http://localhost:8000/api/releases \
  -H 'Content-Type: application/json' \
  -d '{"versionId":1,"workspaceRev":1,"publishedRev":0}'
# → {"ok":true,"releaseNo":1,"publishedRev":1,"sourceVersionId":1,"sourceVersionName":"发布候选-东线",...}

# ⑤ 查看发布记录与某次发布的完整快照（此后改工作区、删版本都不会改变它）
curl -s http://localhost:8000/api/releases
curl -s http://localhost:8000/api/releases/1
```

失败时返回 4xx 与原因、原发布不变。例如审查存在冲突（`HTTP 422`，`entries` 为冲突明细）：

```json
{"ok": false, "reason": "review_failed",
 "error": "审查未通过：存在错误或冲突，原发布不变",
 "errors": [],
 "entries": [{"nfzName": "压线禁飞区", "segIndex": 0, "enterFrac": 0.25,
              "enterTime": "2026-10-01T08:02", "exitTime": "2026-10-01T08:07",
              "altLow": 200.0, "altHigh": 200.0,
              "witness": {"x": 200.0, "y": 100.0, "alt": 200.0}, "instant": false}],
 "first": {"nfzName": "压线禁飞区", "...": "..."}}
```

## 回归测试

判定口径（含凹形禁飞区空隙误报、多部件两段命中、时窗截短见证点移动、线/点/时窗端点擦碰）由 `tests/test_analyze.py` 覆盖，发布流程（成功递增、各类拒绝原因、乐观并发、发布后不可改写）由 `tests/test_releases.py` 覆盖，仅用标准库 `unittest`：

```bash
python3 -m unittest discover -s tests        # 需已 pip install -r requirements.txt
```

## 目录结构

```
app.py                 # Flask 后端：SQLite、时窗/高度/平面冲突计算（Shapely）、发布
tests/test_analyze.py  # 判定口径回归（凹形空隙、两段命中、时窗截断、擦碰）
tests/test_releases.py # 发布回归（递增发布号、拒绝原因、乐观并发、不可变）
templates/index.html   # 单页布局
static/app.js          # 原生 JS：SVG 渲染、拖动、绘制、重算、版本、发布
static/style.css       # 样式
Dockerfile             # python:3.12-slim + gunicorn
docker-compose.yml     # 一条命令启动，端口 8000，卷持久化
requirements.txt
```
