# 客户端加固与提示词保护边界

## 当前已实现

- 冻结二进制不再提供任意 Python 文件执行入口；运行时只能由 MCP/CLI 处理器调用固定白名单脚本。
- `run_skill_script` 在底层再次检查签名授权，避免只依赖外层 handler。
- 冻结包忽略 `LAB_FACTORY_SKILL_ROOT` 和 `LAB_FACTORY_VENDOR_DIR`，不能替换为用户修改的脚本或模块目录。
- 发布包只携带 8 个优化后的运行时 `.pyc`、6 个生成专属 Skill 所需 Schema 和 1 个最终会交付给用户的可见工作流文件。
- 完整工厂 `SKILL.md`、其余 references、eval、开发测试、运行时脚本明文 `.py` 和 `install.py` 源文件不作为数据进入发行包。
- PyInstaller 使用优化级别 2；构建后自动检查归档文件白名单，并尝试执行外部探针验证其被拒绝。
- `RELEASE_BUILD=1` 的 macOS 构建必须提供 Developer ID；Windows `-ReleaseBuild` 必须提供 Authenticode 证书指纹。

## 构建与验证

macOS 本地开发构建：

```bash
bash mcp/lab-skill-factory/build/build_macos.sh
```

macOS 用户发行构建：

```bash
RELEASE_BUILD=1 CODESIGN_IDENTITY="Developer ID Application: ..." \
  NOTARIZE_ZIP=1 bash mcp/lab-skill-factory/build/build_macos.sh
```

Windows 用户发行构建：

```powershell
.\mcp\lab-skill-factory\build\build_windows_installer.ps1 `
  -ReleaseBuild -CodeSigningThumbprint "证书指纹"
```

单独复查现有包：

```bash
python3 mcp/lab-skill-factory/scripts/test_release_security.py \
  --binary mcp/lab-skill-factory/dist/macos/lab-factory
```

## 仍然存在的边界

PyInstaller、字节码优化、代码签名和文件白名单只能增加修改及提取成本。运行在用户电脑上的 Python 模块、生成规则和最终返回给本地 AI 客户端的指令，具备足够能力的用户仍可能观察或逆向。

若要让核心提示词成为真正的服务器端商业机密，下一阶段必须把私有编排、质量评分和模型调用迁移到服务端。本地仅保留文档解析、最小化事实包、DOCX 安全写回和用户可见的专属 Skill；服务器不得把原始系统提示词返回给 MCP 客户端。该改造会改变网络依赖、模型成本和材料隐私边界，需要单独评审后实施。
