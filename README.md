# 实验二：搜索算法

本实验实现 A*、Minimax 和 Alpha-beta，完成迷宫寻路、加权地形、博弈树与宝藏争夺四道题，比较启发函数、节点访问顺序和搜索深度的影响。

## 环境与运行

Python 3.10及以上，仅使用标准库，无需安装额外依赖。本次实验使用Python 3.12.14。

下载仓库后，在代码所在目录运行：

```bash
python run_experiments.py
```

若使用之前建立的Conda环境，可以先执行 `conda activate project1`。运行结束后，`results/` 内的JSON和CSV会更新；报告PDF不会自动重写。耗时受机器及调度影响，重新运行时不必与保存值完全相同。

## 分别运行四题

```bash
python solve.py maze --input examples/maze.json
python solve.py weighted --input examples/weighted.json
python solve.py tree --input examples/tree.json
python solve.py treasure --input examples/treasure_h2.json
python solve.py treasure --input examples/treasure_h4.json
```

输出分别为最短路径坐标数组、最小代价7、最优得分5，以及：

```json
{"best_target": "T2", "best_value": -1}
```

```json
{"best_target": "T3", "best_value": 3}
```

`examples/`中的JSON可复制修改。迷宫及加权题使用 `start`、`end`、`grid`；树使用 `tree_structure`、`children`、`value`，如果提供MAX/MIN标记则按层验证；宝藏题使用 `H` 指定深度，也支持 `grid`、`positions`、`values`，省略时使用课程地图。

## 文件结构

```text
.
├── algorithms.py
├── run_experiments.py
├── solve.py
├── README.md
├── .gitignore
├── examples/
│   ├── maze.json
│   ├── weighted.json
│   ├── tree.json
│   ├── treasure_h2.json
│   └── treasure_h4.json
└── results/
    ├── results.json
    ├── search.csv
    ├── tree.csv
    └── game.csv
```

`algorithms.py`定义算法、状态和课程地图；`run_experiments.py`执行样例、正确性检查和对照实验；`solve.py`负责单题JSON输入输出。`results.json`保存路径、6×6距离矩阵、叶子访问轨迹、首步收益、节点数、耗时与测试状态；CSV用于查看和复核各组实验。报告按课程要求另外提交。

## 实现约定

- A*只能四方向移动，移动代价为进入下一格的权重，起点不收费。无解时迷宫接口返回空列表，加权接口返回-1。
- 题二的终点E代价为0，采用安全下界 `min_cost * max(Manhattan-1, 0)`；若中间也有零代价格，则保守回退h=0。普通正权图采用最小进入代价乘曼哈顿距离。
- 基线同f按入队顺序处理；优化方案同f优先较大g。节点数为有效出队次数，包含终点，不计过期队列项。
- 题三根节点为MAX，MAX/MIN逐层交替，默认从左到右访问；逆序仅用于对照。完整样例采用题目第10至12页结构，第9页简图省略了重复的MAX子树。
- Alpha-beta仅在α≥β时剪枝。节点数含递归调用和叶子，剪枝次数只计确实跳过剩余兄弟的事件。
- 综合题宝藏价值为9、6、7、7，A/B/宝藏格进入代价均为1。深度单位为单次玩家行动；只收集选定宝藏，另一玩家不阻路。
- 收益为价值减移动代价，允许负数。叶子返回A累计收益减B累计收益。即时收益排序只用于改变访问次序，不替代博弈求解。
- 距离矩阵提前计算并复用，对角线为0。不可达候选不作为合法动作；若全部不可达则结束当前分支并返回当前收益差。

## 对照实验与检查

- 250个随机地图，每个测试4种配置，共1000组，与独立Dijkstra核对；包含中间零代价格。
- 距离矩阵全部36个元素单独核对。
- 100棵随机树、100组宝藏价值，比较Minimax和Alpha-beta的结果。
- 100个不同位置、收益、剩余集合和当前玩家的状态，用独立穷举检查最优值与最优首步。
- 4个边界用例、5个非法输入用例、5份JSON示例检查。

随机种子固定为42。每个计时配置预热5次，再运行31次，取微秒中位数，不含文件读写；距离矩阵的预计算独立计时。综合题H=4时，Minimax访问65个节点，原顺序Alpha-beta为47个，按即时收益排序后为37个，最优结果不变。

扩展实验包含40×40空地图的同f处理，以及更短步数不等于更低代价的加权绕路场景。节点数适合比较搜索开销；优化效果依赖输入，不按单一场景推断所有地图的表现。
