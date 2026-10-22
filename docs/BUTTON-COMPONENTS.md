# 按钮组件模板

所有按钮来自 [Button.tsx](../src/components/Button.tsx)，统一样式位于 [button-system.css](../src/button-system.css)。构建前自动执行按钮规范检查。

```tsx
import {Button, FileButton} from './components/Button';

<Button variant="primary" busy={saving} busyLabel="正在保存…" onClick={save}>保存设置</Button>
<Button variant="secondary" onClick={cancel}>取消</Button>
<Button variant="secondary" size="compact">表格操作</Button>
<Button variant="icon" aria-label="刷新" onClick={refresh}><RefreshCw/></Button>
<Button variant="link" onClick={openDetails}>查看详情</Button>
```

默认操作按钮高度40px、圆角12px、字号13px、最小宽度120px；手机最小宽度112px。紧凑操作32px，图标按钮40×40px。长文案可按内容拓宽，加载标签与默认文案共享同一网格占位，切换状态不改变宽度。

`reserveLabel` 可预留非加载文案的宽度。导航、页签、数据卡片是独立语义类型，其布局由各自容器控制；不混用普通提交按钮的固定高度。时间轴只允许通过 `TimelineButton` 的时间坐标属性控制占用条。

编辑表单放入 `ActionDialog`。弹窗挂载到独立层，保留原按钮工具栏的位置；Escape/关闭仍执行未保存确认，提交中不能关闭。弹窗不使用会缩小内容区宽度的页面滚动锁。

禁止新增原生按钮、按钮私有内联材质与尺寸。代码检查会阻止这两类情况；`npm run build` 自动运行检查。响应式断点、业务数据更新或按钮权限变化仍会产生有意义的布局变化，不应通过固定屏幕坐标阻止正常页面排版。
