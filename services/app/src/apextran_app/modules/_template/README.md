# _template — 新模块骨架

复制本目录到 `modules/<你的模块名>/`,按限界上下文填充,`main`/`worker` 会自动发现。

```
modules/<name>/
├── domain/          # 纯模型/规则,零 IO
│   └── models.py
├── ports.py         # 依赖的抽象接口(数据源/外部服务)
├── adapters/        # 端口的实现(mock / 真源)
├── service.py       # 用例编排
├── provider.py      # 组装单例(cache/source 注入),避免 wiring 循环导入
├── ingest.py        # register_jobs(scheduler):登记定时任务(可选)
├── router.py        # APIRouter(prefix="/api/v1/<name>")
└── wiring.py        # MODULE = ModuleSpec(name, router, register_jobs)
```

## 三条边界铁律(务必遵守)

1. **不 import 其他模块的内部实现**;协作只经对方 `service.py` 公开方法、`shared/`、或消息。
2. **六件套自包含**,`main.py` 只负责注册。
3. **共享只下沉到 `shared/`**;DB 表用 `<name>_*` 前缀。

> 目录名以 `_` 开头会被 `discover_modules()` 跳过,所以这个模板不会被挂载。
