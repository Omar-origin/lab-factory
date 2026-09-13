# 独立可行性样例

日期：2026-09-13。

- native-image-and-three-line-table.docx：真实图片与原生三线表的可编辑样例。
- native-image-and-three-line-table.pdf：LibreOffice 转换的已查看预览。
- public-docs-screenshot.png：本次实际访问 https://lab.elyther.top/docs 的截图，不是实验运行证据。
- validation.json：已验证 1 张原生表格、12 个单元格、1 张 inline 图片、图片字节与截图一致；上/下边框 1.5pt，表头下边框 0.5pt，无竖线。
- build-demo.cjs：独立构件生成脚本，依赖 docx npm 包，不是生产引擎实现。

首次 PDF 转换缺少中文字体，配置本机已有 SimSong 字体后已恢复并检查。字体与具体编辑器是正式验收项。

尝试打开本机 WPS 时工具异常缓慢，最终仅取得首页，未完成样例在 WPS 中打开、编辑和保存的验证；没有改动已有用户文档。Windows Word/WPS、macOS Word 以及不同模型宿主亦未进行端到端验证。

此样例不证明现有报告生成流程已经支持上述操作；正式接入方案见项目 docs/design 下的两份设计。
