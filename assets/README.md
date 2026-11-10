# assets/

`shennong_files/` 是 14 Pro 修补资源的缓存目录，**不提交进仓库**（约 310 MiB）。

```bat
python tools\assets.py fetch            :: 下载缺失资源（镜像链 + 断点续传 + 大小校验）
python tools\assets.py list             :: 查看缓存状态与镜像顺序
python tools\assets.py verify           :: 校验大小
python tools\assets.py mirrors --probe  :: 探测哪条镜像通
```

来源：上游 [XHR222/14PRO_SHALLOW_ROM](https://github.com/XHR222/14PRO_SHALLOW_ROM)
的 `shennong_files/`。Gitee 版默认按镜像链下载，顺序：

```
gitee:h-shennong/14PRO_SHALLOW_ROM  →  ghfast.top  →  gh-proxy.com
→  ghproxy.net  →  raw.githubusercontent.com
```

想钉死一条（或调整顺序），在 `config.ini` 里写：

```ini
[shennong]
asset_base=https://gitee.com/h-shennong/14PRO_SHALLOW_ROM/raw/main/shennong_files/
;; 或追加前缀到链首，仍保留回落
asset_mirrors=https://ghfast.top/
```

Gitee 镜像仓库的建法见 [../docs/GITEE.md](../docs/GITEE.md#5-让镜像链第-1-条真正生效强烈建议)。

`root_images/` 里的 ROOT 补丁与 TWRP 是**要提交**的（打包阶段直接用），
不要被上面 `shennong_files/` 的忽略规则带走。
