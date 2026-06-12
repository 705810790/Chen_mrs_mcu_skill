# Chen_mrs_mcu_skill

Chen_mrs_mcu_skill 是一个面向 AI 和脚本自动化的 MounRiver Studio 单片机开发 Skill。它把沁恒 WCH CH32V/CH32X 工程中的编译、重新编译、下载烧录、工程检查拆成 `doctor / inspect / make / remake / download` 这类短命令，让 AI 可以像操作 Linux `make` 工程一样接入 MounRiver 项目。

## 背景

MounRiver Studio 本质上基于 Eclipse CDT managed build。直接运行工程目录里的 `Makefile` 有时并不等价于在 IDE 里点击“编译”按钮，因为 IDE 会先导入工程、刷新 managed build 文件，再执行对应 configuration 的构建。

AI 直接猜 MounRiver 的内部命令很容易出错：路径、工具链环境、生成 Makefile、OpenOCD 配置都可能不一致。Chen_mrs_mcu_skill 的目标是把这些细节封装成一个稳定工具，让 AI 只需要调用统一命令即可完成编译和下载准备。

## 适用场景

- 使用 MounRiver Studio 开发沁恒 CH32V/CH32X RISC-V MCU
- 需要让 AI 自动编译 MounRiver 工程
- 需要复刻 IDE 点击“编译”按钮的构建行为
- 需要检查工程结构、产物、链接脚本、启动文件
- 需要通过 WCH-Link/WCH-LinkE 和 OpenOCD 下载固件
- 需要在没有下载器时先 dry-run 检查下载命令

## 一键安装

安装到当前 AI 环境：

```powershell
帮我安装 https://github.com/705810790/Chen_mrs_mcu_skill.git 的skill
```

如果需要设置为全局在任意文件夹调用的 skill：

```powershell
帮我安装 https://github.com/705810790/Chen_mrs_mcu_skill.git 的skill 到全局目录下
```

## 项目结构

```text
Chen_mrs_mcu_skill/
├── README.md
├── SKILL.md                         # Codex Skill 入口说明
├── SKILL.zh-CN.md                   # 中文副本
└── scripts/
    └── wch_mrs_tool.py              # MounRiver 编译/下载工具
```

## 快速开始

查看帮助：

```powershell
python scripts\wch_mrs_tool.py --help
```

检查 MounRiver 工具链：

```powershell
python scripts\wch_mrs_tool.py --mrs "E:\MounRiver_Studio" doctor
```

检查工程：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" inspect
```

编译：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" make
```

重新完整编译：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" remake
```

下载 dry-run：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" download --dry-run
```

## AI 推荐用法

给 AI 使用时，建议按固定流程执行：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" doctor
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" inspect
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" make --dry-run
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" make
```

需要清理并重新编译时：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" remake
```

下载前先 dry-run：

```powershell
python scripts\wch_mrs_tool.py --project "D:\path\to\FreeRTOS_Core" --mrs "E:\MounRiver_Studio" download --dry-run
```

规则：

- AI 必须先运行 `doctor` 和 `inspect`，再执行 `make`。
- 下载前必须先运行 `download --dry-run`。
- `make` 默认使用 MounRiver/Eclipse CDT headless build，更接近 IDE 编译按钮。
- `download` 默认使用 MounRiver 自带 OpenOCD 和 `wch-riscv.cfg`。
- 没有下载器时出现 `WLink Open Error` 是硬件未连接，不是编译错误。

## 常用命令

```powershell
python scripts\wch_mrs_tool.py doctor                  # 检查工具链
python scripts\wch_mrs_tool.py inspect                 # 检查工程
python scripts\wch_mrs_tool.py make                    # 编译
python scripts\wch_mrs_tool.py remake                  # 清理后重新编译
python scripts\wch_mrs_tool.py rebuild                 # remake 的别名
python scripts\wch_mrs_tool.py clean                   # 清理
python scripts\wch_mrs_tool.py download --dry-run      # 打印下载命令
python scripts\wch_mrs_tool.py download                # 下载固件
python scripts\wch_mrs_tool.py config-example          # 生成配置示例
```

兼容命令：

```powershell
python scripts\wch_mrs_tool.py build                   # 等同于 make
python scripts\wch_mrs_tool.py flash                   # 等同于 download
```

## 本地配置

可以在工程目录放置 `.wch_mrs_tool.json`：

```json
{
  "mrs_root": "E:\\MounRiver_Studio",
  "project": "D:\\path\\to\\FreeRTOS_Core"
}
```

生成配置示例：

```powershell
python scripts\wch_mrs_tool.py config-example
```

不要把包含个人路径的 `.wch_mrs_tool.json` 提交到公共仓库。

## 安装为 Codex Skill

把整个 `Chen_mrs_mcu_skill` 文件夹复制到 Codex skills 目录。Codex 触发该 Skill 后，会优先使用 `scripts/wch_mrs_tool.py` 操作 MounRiver 工程。

推荐给 AI 的提示方式：

```text
使用 Chen_mrs_mcu_skill 编译这个 MounRiver 工程，先检查环境，再执行 make。如果失败，帮我分析第一条真实错误。
```

## 注意事项

- `make` 不是简单调用已有 `obj\Makefile`，默认会通过 MounRiver `eclipsec.exe` 执行 headless build。
- 只有确认不需要刷新 MounRiver generated Makefile 时，才使用 `make --backend make`。
- 下载功能需要 WCH-Link/WCH-LinkE 和驱动正常。
- 没有下载器时可以使用 `download --dry-run` 检查命令。
- 不要手动修改 `.o`、`.d`、`.elf`、`.hex` 等构建产物。
