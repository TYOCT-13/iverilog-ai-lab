# Valid-Ready 握手规则

- 传输仅在 `valid && ready` 同时为 1 时发生。
- 下游未 ready 时，`out_valid` 和 `out_data` 必须保持稳定。
- 复位后 `out_valid=0`，不能凭空产生数据。
- `valid` 不能依赖 `ready` 才产生；反向依赖可能形成组合环路。
