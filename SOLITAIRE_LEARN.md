# Flet Solitaire Tutorial Learnings

## 结论

Flet 没有暴露全部 Flutter 高级组件，但普通控件已经足够组合复杂交互和自定义布局。关键工具是 `Stack` 绝对定位、`GestureDetector`、控件继承、挂载生命周期和显式更新。

## 可复用能力

### Stack 绝对定位

`Stack` 子控件可以通过 `left` 和 `top` 自行定位：

```python
card = ft.Container(left=100, top=40, width=80, height=120)
stack = ft.Stack([card])
```

运行时修改位置后必须更新控件或父控件：

```python
card.left = 120
card.top = 60
card.update()
```

这允许实现拖拽、卡牌堆叠、自由画布和手工 Masonry 布局。

### 控件顺序就是层级顺序

`Stack.controls` 中越靠后的控件越靠上。需要把某个控件移到顶层时，可以调整列表顺序：

```python
stack.controls.remove(card)
stack.controls.append(card)
stack.update()
```

### GestureDetector 支持复杂手势

常用事件包括：

```python
on_tap
on_double_tap
on_long_press
on_pan_start
on_pan_update
on_pan_end
```

拖拽时可在 `on_pan_update` 中根据 `local_delta` 更新 `left/top`。高频手势优先调用目标控件的 `update()`，不要无条件刷新整个 Page。

### 可以继承 Flet 控件

复杂组件可以继承普通 Flet 控件，并保存自己的状态和方法：

```python
class MasonryGallery(ft.Stack):
    def __init__(self):
        super().__init__()
        self.items = []
        self.column_heights = []
```

这适用于需要内部状态、布局算法和生命周期管理的控件。但简单页面优先使用函数组合，避免为少量布局引入不必要的类。

### did_mount 与 will_unmount

依赖已挂载 Page/session 的工作必须在 `did_mount()` 后启动，而不是在 `__init__()` 中启动：

```python
class AsyncControl(ft.Container):
    def did_mount(self):
        self.page.run_thread(self.load)

    def will_unmount(self):
        self.cancelled = True
```

这与项目的 `async_image` 规则一致：控件挂载后才启动后台加载，卸载后丢弃后台结果。不要用固定 sleep 或裸 daemon thread 绕过生命周期。

### 显式更新规则

修改控件属性或控件树后，必须调用：

```python
control.update()
```

或：

```python
page.update()
```

局部更新优先于全页更新。会修改 UI 的后台任务使用 `page.run_thread()`，并在结果仍有效时更新。

### 隐式动画

Flet 可以对位置等属性使用隐式动画：

```python
card.animate_position = ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC)
card.left = new_left
card.top = new_top
card.update()
```

动画由 Flutter 前端执行，通常比 Python 逐帧修改稳定。大量控件同时动画前必须实测性能和残影，不应默认启用。

## 画廊瀑布流

Core 已为列表条目提供：

```python
comic.cover_width
comic.cover_height
comic.cover_aspect_ratio
```

比例必须经过保护：

```python
def safe_cover_ratio(comic) -> float:
    ratio = comic.cover_aspect_ratio or 0.72
    return max(0.4, min(2.0, ratio))
```

缺失尺寸回退 `0.72`，异常尺寸不得制造极高或极宽控件。

### 方案一：Stack 绝对定位

为每列维护当前高度，将下一张卡片放入最短列：

```python
column_heights = [0.0] * column_count

for comic in comics:
    column = min(range(column_count), key=column_heights.__getitem__)
    ratio = safe_cover_ratio(comic)
    card_height = column_width / ratio
    left = column * (column_width + spacing)
    top = column_heights[column]
    column_heights[column] += card_height + spacing
```

然后设置每张卡片的 `left/top/width/height`，并让 Stack 高度等于 `max(column_heights)`。

优点：真正自由定位，可以做重新排布动画。

缺点：没有列表虚拟化，需自行处理总高度、resize、坐标和大量控件性能。

### 方案二：Row + 多个 Column

建立多个等宽 Column，每张卡片进入当前最短列：

```python
columns = [ft.Column(expand=True, spacing=spacing) for _ in range(column_count)]
column_heights = [0.0] * column_count

for comic in comics:
    ratio = safe_cover_ratio(comic)
    column = min(range(column_count), key=column_heights.__getitem__)
    columns[column].controls.append(
        ft.Container(
            content=make_gallery_card(page, comic, mode="masonry"),
            aspect_ratio=ratio,
        )
    )
    column_heights[column] += 1 / ratio

masonry = ft.Row(columns, vertical_alignment=ft.CrossAxisAlignment.START)
```

因为列宽相同，`1 / aspect_ratio` 可以作为归一化高度权重。

优点：实现小、无需手工坐标、可继续放在现有 `ListView` 中，分页条也可自然位于其后。

缺点：控件树按列组织，键盘和无障碍阅读顺序未必严格按视觉上的行顺序。

### 当前决策

FletViewer 第一版真正瀑布流优先使用 `Row + 多个 Column + 最短列算法`。当前 EH 每页通常只有 25 到 50 个画廊，不需要为自由定位和动画引入复杂 Stack 布局。

动态追加不能修改已有 `Column.controls`，实测会让该列全部闪烁。连续瀑布流采用“每列独立 TailHost”方案：每列初始末尾放一个空 `Container`；下一页先按全局累计列高分配卡片，再把每列的新卡片作为一个纵向批次写入该列当前空 Host，并在批次末尾创建下一个空 Host。每次只更新此前为空的 Host，旧 Column 和旧卡片不参与 patch。

```text
Column 0          Column 1          Column 2
├─ old cards      ├─ old cards      ├─ old cards
└─ TailHost       └─ TailHost       └─ TailHost
   ├─ new batch      ├─ new batch      ├─ new batch
   └─ NextHost       └─ NextHost       └─ NextHost
```

这个结构看似反常，但同时满足连续最短列排列、无分页块空隙和旧内容不闪烁。resize/列数变化允许全量重建，因为它是低频操作；正常分页禁止修改旧列。

主页、订阅、热门、排行榜、收藏和搜索必须共用同一个 Masonry builder，不能各自维护布局算法。Masonry 属于展示逻辑，应放在 `app/`，不放进 `core/`。

## 项目约束

- 不要因为 Flet 缺少某个 Flutter 高级组件就立即手写逐帧 Python 动画。
- 普通布局能解决时，优先普通布局；只有需要自由坐标时才使用 Stack。
- 自定义控件的资源在 `did_mount()` 启动，在 `will_unmount()` 失效。
- 控件属性改变后必须更新；高频路径优先局部更新。
- 大量绝对定位控件没有自动虚拟化，必须限制数量或窗口化。
- 瀑布流 resize 只重新计算布局，不重新请求 Provider 数据。
- 画廊封面继续走 `async_image()`，不能直接把 bytes 或本地路径交给 `ft.Image`。
