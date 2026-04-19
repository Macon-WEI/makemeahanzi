# 字体 A 单笔 contour 先验 → 字体 B contour 片段搜索

这套工具实现的是 **跨字体近似迁移**：

- 不直接迁移 A 的 contour 点索引到 B。
- 而是迁移“这一笔的几何+相对位置先验”，再在 B 里重搜索。

## 方法（当前实现）

给定字体 A 的某一笔（来自 `graphics.txt` 的 `strokes[i]`）：

1. **形状先验**：采样这笔的边界点，构造归一化形状模板。
2. **位置先验**：记录这笔在整字坐标中的相对中心与相对尺寸。
3. 在字体 B 的每个候选字符里：
   - 提取 glyph contours（支持 simple/composite glyph 的展开轮廓绘制）；
   - 在 contour 上做滑窗；
   - 计算综合分数：
     - 形状项（对称 Chamfer）
     - 位置项（窗口相对中心/尺寸 vs 先验）
     - 曲率项（turning-angle 序列 L2）
4. 输出 top-k 片段及分项分数。

> 这更接近“迁移对应关系”而非“迁移点编号”。

## 依赖

```bash
pip install -r contour_search/requirements.txt
```

## 下载字体 B（思源宋体）

```bash
python contour_search/download_source_han_serif.py
```

默认会下载 `SourceHanSerifSC-Regular.otf` 到：

- `fonts/SourceHanSerifSC-Regular.otf`

如果你本地已有思源宋体文件，直接传 `--font-b` 即可。

## 使用示例

以 `永` 的第 3 笔（索引 2）为先验，在字体 B 的 `永泳咏` 三个字中搜索：

```bash
python contour_search/search_contour_segments.py \
  --char-a 永 \
  --stroke-index 2 \
  --graphics graphics.txt \
  --font-b fonts/SourceHanSerifSC-Regular.otf \
  --candidate-chars 永泳咏 \
  --sample-points 64 \
  --window-points 64 \
  --stride 8 \
  --w-shape 1.0 \
  --w-pos 0.7 \
  --w-curv 0.4 \
  --topk 10
```

输出字段：

- `glyph_kind`: `simple` / `composite` / `unknown`
- `score`: 综合分数（越小越相似）
- `shape` / `pos` / `curv`: 分项分数

## 局限与下一步

- 目前仍是单笔、无全局多笔联合分配。
- 可继续加入：
  - 多笔互斥分配（避免不同笔抢同一 contour 片段）
  - component-aware 的更强约束
  - DTW/学习型 embedding 等更稳健的曲线匹配
