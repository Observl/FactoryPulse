# Liquid Glass 组件接入

更新：2026-10-24。

本次将 Figma 中适合的组件材质同步到本地 React 项目；继续保留现有业务流程、账号验证和数据来源。

| 设计组件 | 项目落点 |
| --- | --- |
| IconRail / WorkspacePanel / DataSpaceCard | `src/WorkspaceNavigation.tsx`，共享玻璃边缘、半透明底板和背景模糊 |
| KPI 卡片 | `src/components/MetricCard.tsx`，已用于真实工作台的待办分类统计 |
| Panel / 工具栏 / 菜单 | `src/liquid-glass.css`，通过既有语义类统一材质 |
| ActionDialog / 设备详情 / 同步说明 | 既有弹窗组件，玻璃浮层与背景模糊；保留焦点管理 |
| DotMatrixColumns | `src/components/DesignCharts.tsx` 的 DotHistogram，已替换设备风险与温度对比对应柱图 |
| GlowHorizontalBars | 同文件 GlowBars，已用于风险排行，支持鼠标与键盘打开设备 |
| FrequencyCurve | 设备详情工况与风险曲线，单色线条、无采样点、保留渐变面积填充 |
| DatabaseUpdateGrid | ContributionCalendar，已用于历史版本区域，以归档时间按天计数 |

材质约束：白色图表与表格底板；所有按钮无渐变；橙色数据条可以渐变；不恢复流动、抖动或采样点动画。玻璃主要依靠半透明填充、背景模糊、内缘高光与柔和阴影。支持减少透明度、提高对比度及减少动态偏好。

数据库色板直接沿用参考图：`#EFF2F5`、`#ACEEBB`、`#4AC26B`、`#2DA44E`、`#116329`。53 周 × 7 天；18px 格子、3px 圆角、5px 间隙。颜色档位为 0、1–5、6–10、11–15、16 次以上归档更新。未来日期不代表已统计的零更新日。

开发效果页：`http://127.0.0.1:5173/?component-preview=1`。复用同一导航、按钮、卡片、弹窗与图表组件；明确使用示例数据，不请求或更改业务记录。仅开发模式可用，正式构建仍使用正常登录入口。

验证：统一按钮检查、TypeScript 检查及 Vite 构建通过。浏览器确认 0 个渐变按钮、371 个日历格、白色图表底板、无横向溢出，弹窗可打开及关闭。真实业务页面已登录，但当前读取业务数据的接口超时，未将示例数据注入真实页面。
