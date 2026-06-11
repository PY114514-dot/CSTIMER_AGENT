# 07 关键原型 (HTML + JS)

> 打开方式：直接在浏览器双击 `prototype/dashboard/index.html`，或：
>
> ```bash
> cd "d:/CSTIMER 魔方助手/prototype/dashboard"
> python -m http.server 8080
> # 访问 http://localhost:8080
> ```

## 7.1 已包含的视图

- 每日目标环形进度 + 推荐说明
- 当前 Session 卡片：avg3、阶段耗时对比、趋势箭头
- AI 教练卡片：瓶颈标签、3 条训练建议
- 阶段耗时堆叠条形图（12 把 × 4 阶段）
- 停顿热图（12 把 × 15 个 1s 时间窗）
- 停顿阶段分布条 + 掉速倍数
- 历史 avg3/avg5 折线（9 个 Session）
- 今日训练项清单（点击勾选可切换 done 状态）

## 7.2 文件结构

```
prototype/
├── dashboard/
│   └── index.html        # 单文件看板（HTML+CSS+ES module 引入 mock）
└── mock/
    └── mock-data.js      # 模拟一个 Session 的真实数据
```

## 7.3 与真实后端的对接点

打开 `index.html` 中的 `<script type="module">` 块，将

```js
import { todayDashboard as D } from './mock/mock-data.js';
```

改为：

```js
const D = await fetch('/api/dashboard/today').then(r => r.json());
```

字段命名严格遵循 `docs/06-frontend-dashboard.md` §6.4 的接口契约，
因此前后端联调无需做字段映射。

## 7.4 后续原型迭代

- 用真实数据替换 mock 后，删除 `prototype/mock/` 目录
- 把 `index.html` 拆为 React 组件：
  - `<Dashboard>` 拆为 5 个子组件对应上面的视图
  - 用 TanStack Query 替换 `fetch`
  - 用 shadcn/ui 替换手写 CSS
