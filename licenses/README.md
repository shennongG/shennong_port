# licenses/

`tools/` 与 `assets/root_images/` 里随包分发的第三方组件，其许可证正文放在这里。
对应关系与版权人见仓库根目录的 [NOTICE.md](../NOTICE.md)。

| 文件 | SPDX | 适用于 | 官方获取地址 |
| --- | --- | --- | --- |
| `GPL-2.0.txt` | GPL-2.0-only | aria2、erofs-utils、e2fsprogs（部分）、JRE（GPL-2.0+CE） | https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt |
| `LGPL-2.1.txt` | LGPL-2.1-only | 7-Zip、e2fsprogs（lib 部分） | https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt |
| `GPL-3.0.txt` | GPL-3.0-only | TWRP 等 GPLv3 组件 | https://www.gnu.org/licenses/gpl-3.0.txt |
| `Apache-2.0.txt` | Apache-2.0 | apktool、payload-dumper-go、Android 分区工具 | https://www.apache.org/licenses/LICENSE-2.0.txt |
| `BSD-3-Clause.txt` | BSD-3-Clause | Zstandard | https://github.com/facebook/zstd/blob/dev/LICENSE |
| `7-Zip-license.txt` | LGPL-2.1 + unRAR restriction | 7-Zip（含 Android 侧 7zzs） | https://www.7-zip.org/license.txt |

说明：

* 这些文件均为**原样下载的许可证正文**，未做改动；
* 本项目自身代码按 MIT 发布，正文见 [`../LICENSE`](../LICENSE)；
* 发行卡刷包时，打包脚本会把 `NOTICE.md` 与本目录一起放进 zip 的 `NOTICE/`，
  以满足「随二进制提供声明」的要求；
* GPL/LGPL 组件的源码获取方式见 `NOTICE.md` 第 3 节。
