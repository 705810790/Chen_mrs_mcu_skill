---
name: wch-ch32v-mounriver
description: 用于沁恒 WCH CH32V RISC-V 单片机的 MounRiver Studio 工程开发，尤其适用于 CH32V303/CH32V307 项目的工程检查、命令行编译、编译错误诊断、启动文件和链接脚本分析，以及后续接入 WCH-Link 下载/调试流程。当用户提到 MounRiver Studio、沁恒、CH32V、CH32V303、CH32V307、RISC-V MCU、编译失败、下载烧录或希望 AI 接入单片机开发流程时使用。
---

# 沁恒 CH32V MounRiver 工程助手

使用本 skill 时，优先调用配套命令行工具，不要让 AI 手工猜测 MounRiver Studio 的内部编译命令。

本 skill 的组织方式参考 `LeoKemp223/embed-ai-tool`：skill 负责工作流说明，脚本负责稳定执行；工具路径通过参数、配置文件、环境变量和自动探测获得；命令结果尽量提供结构化输出，方便 AI 读取和交接。

## 工具入口

配套工具为：

```powershell
python scripts\wch_mrs_tool.py --help
```

常用命令别名：

```text
make      编译，等同于 build
remake    重新完整编译，等同于 rebuild
rebuild   重新完整编译
download  下载，等同于 flash
```

默认以当前目录作为工程目录。也可以通过 `--project` 指定工程，通过 `--mrs` 指定 MounRiver Studio 安装目录。

工具路径解析顺序：

1. 命令行参数：`--mrs`
2. 配置文件：`.wch_mrs_tool.json`
3. 环境变量：`WCH_MRS_ROOT`、`MOUNRIVER_STUDIO_ROOT`、`MOUNRIVER_HOME`、`MRS_ROOT`
4. 常见安装目录
5. 系统 `PATH`

生成配置文件示例：

```powershell
python scripts\wch_mrs_tool.py config-example
```

可将输出保存为工程目录下的 `.wch_mrs_tool.json`，但不要把包含个人路径的配置文件提交到公共仓库。

## 标准流程

第一步，检查 MounRiver 和工具链：

```powershell
python scripts\wch_mrs_tool.py doctor
```

需要结构化输出时使用：

```powershell
python scripts\wch_mrs_tool.py doctor --json
```

第二步，检查工程结构：

```powershell
python scripts\wch_mrs_tool.py inspect
```

重点查看：

- 是否找到工程目录
- 是否找到 Makefile
- 是否找到 `.elf`、`.hex`、`.bin` 产物
- 是否找到链接脚本 `.ld`
- 是否找到 startup 启动文件
- 是否能推断芯片型号

第三步，先 dry-run 编译命令：

```powershell
python scripts\wch_mrs_tool.py make --dry-run
```

确认工作目录和编译命令正确后，再执行真实编译：

```powershell
python scripts\wch_mrs_tool.py make
```

需要清理后重新完整编译时使用：

```powershell
python scripts\wch_mrs_tool.py remake
```

工具默认优先使用 MounRiver/Eclipse CDT headless build，也就是 `eclipsec.exe -application org.eclipse.cdt.managedbuilder.core.headlessbuild`。这比直接运行已有 `obj\Makefile` 更接近 MounRiver Studio 中点击编译按钮的行为，因为它会导入工程、刷新 managed build 文件，再执行对应 configuration 的构建。

只有在确认不需要 MounRiver 重新生成 Makefile 时，才使用：

```powershell
python scripts\wch_mrs_tool.py make --backend make
```

## 工程画像

`doctor --json` 和 `inspect --json` 会输出类似 Project Profile 的结构，方便 AI 在多轮任务中交接：

- `workspace_root`：工程根目录
- `workspace_os`：操作系统
- `build_system`：构建系统，当前为 `mounriver-make`
- `toolchain`：工具链，当前为 `wch-riscv-gcc`
- `target_mcu`：从源码、链接脚本或工程文件中推断的芯片型号
- `artifact_path`：当前检测到的主要产物路径
- `artifact_kind`：产物类型，例如 `elf`

不要在 skill 中写死某台电脑的 MounRiver 安装路径或工程路径。用户私有路径应放在命令行参数、环境变量或本地 `.wch_mrs_tool.json` 中。

## 修改原则

优先修改用户工程源码、头文件、工程内配置、链接脚本和启动文件。

谨慎修改以下文件：

- MounRiver 自动生成的 Makefile
- `.d` 依赖文件
- `.o` 目标文件
- `.elf`、`.hex`、`.bin` 构建产物
- IDE 自动生成配置

如果必须修改 Makefile，先说明原因，并尽量保持原有变量、路径风格和 MounRiver 生成结构。

修改 startup 或 linker script 前，必须先检查：

- 芯片具体型号
- Flash/RAM 地址和大小
- 中断向量表
- 栈、堆、FreeRTOS heap 配置
- 工程当前使用的是哪个 startup 文件

## 编译失败诊断流程

编译失败时，先判断错误阶段：

- 编译错误：通常来自 `.c`、`.h`、宏定义、include 路径
- 汇编错误：通常来自 startup、内联汇编、RISC-V 指令或汇编语法
- 链接错误：通常是 undefined reference、重复定义、section 溢出、链接脚本问题
- objcopy/size 错误：通常是前面 ELF 生成失败或产物路径错误

处理规则：

1. 先找第一条真实错误，不要被后续级联错误带偏。
2. include 找不到时，先检查工程 include 路径，不要直接复制头文件。
3. undefined reference 时，先确认源文件是否加入构建，而不是只看函数声明。
4. section 溢出时，检查 `Link.ld`、Flash/RAM 占用、FreeRTOS heap、全局数组。
5. startup 相关错误时，确认芯片型号和 startup 文件是否匹配。

## 下载烧录

下载烧录通过 MounRiver 自带 OpenOCD 和 WCH RISC-V 配置实现：

```powershell
python scripts\wch_mrs_tool.py download --dry-run
```

`--dry-run` 只打印命令，不连接硬件。无下载器时也可以使用它确认产物和 OpenOCD 配置是否正确。

真实下载：

```powershell
python scripts\wch_mrs_tool.py download
```

默认会自动选择最新的 `obj/*.elf`、`obj/*.hex` 或 `obj/*.bin`，并优先使用 MounRiver 的 `toolchain\OpenOCD\bin\wch-riscv.cfg`。

常用选项：

```powershell
python scripts\wch_mrs_tool.py download --file obj\FreeRTOS.hex
python scripts\wch_mrs_tool.py download --format hex
python scripts\wch_mrs_tool.py download --no-verify
```

如果没有插入 WCH-Link/WCH-LinkE，OpenOCD 可能输出 `WLink Open Error`。这说明 OpenOCD 和配置已启动，但未发现下载器硬件；不要把它当成编译错误。

## 给 AI 的工作习惯

遇到用户要求“编译”“检查工程”“修编译错误”时：

1. 先运行 `doctor`。
2. 再运行 `inspect`。
3. 再运行 `make --dry-run`。
4. 确认路径正确后运行 `make`；需要重新完整编译时运行 `remake`。
5. 根据编译日志定位问题。
6. 修改代码后重新编译验证。

不要在没有验证命令输出的情况下宣称编译成功。
