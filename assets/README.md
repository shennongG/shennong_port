# assets/

`shennong_files/` 是 14 Pro 修补资源的缓存目录，**不提交进仓库**（约 310 MiB）。

```bat
python tools\assets.py fetch     :: 下载缺失资源（断点续传 + 大小校验）
python tools\assets.py list      :: 查看缓存状态
python tools\assets.py verify    :: 校验大小
```

来源：上游 [XHR222/14PRO_SHALLOW_ROM](https://github.com/XHR222/14PRO_SHALLOW_ROM)
的 `shennong_files/`。国内网络可用镜像：

```ini
[shennong]
asset_base=https://ghfast.top/https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
```
