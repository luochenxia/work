"""实验二：搜索算法。仅使用 Python 标准库。"""
from dataclasses import dataclass, field
import heapq
import itertools
import math

DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))


@dataclass
class Stats:
    nodes: int = 0  # A*: 有效出队数（含终点）；博弈：递归调用数（含叶子）
    leaves: int = 0
    cutoffs: int = 0  # 确实跳过剩余兄弟的次数


def astar(grid, start, goal, heuristic="manhattan", prefer_deep=False):
    """数字为进入代价，X/None 为障碍。返回 (路径, 代价, 统计)。

    目标为零代价格时 h=max(曼哈顿距离-1,0)*最小正代价。
    其他位置含零代价格时回退 h=0，保证不会高估。
    """
    stats = Stats()
    if heuristic not in ("zero", "manhattan"):
        raise ValueError("heuristic 必须为 zero 或 manhattan")
    if not grid or not grid[0]:
        return [], -1, stats
    rows, cols = len(grid), len(grid[0])
    if any(len(row) != cols for row in grid):
        raise ValueError("地图必须为矩形")

    def valid(p):
        r, c = p
        return 0 <= r < rows and 0 <= c < cols and grid[r][c] not in ("X", None)

    if not valid(start) or not valid(goal):
        return [], -1, stats
    costs = [float(v) for row in grid for v in row if v not in ("X", None)]
    if any(v < 0 or not math.isfinite(v) for v in costs):
        raise ValueError("代价必须为有限非负数")
    others = [float(grid[r][c]) for r in range(rows) for c in range(cols)
              if (r, c) != goal and valid((r, c))]
    scale = min(others, default=0)
    goal_cost = float(grid[goal[0]][goal[1]])
    if goal_cost > 0:
        scale = min(scale, goal_cost)

    def h(p):
        if heuristic == "zero":
            return 0
        distance = abs(p[0] - goal[0]) + abs(p[1] - goal[1])
        return scale * max(0, distance - (goal_cost == 0))

    serial = itertools.count()
    queue = [(h(start), 0, next(serial), 0, start)]
    best, parent = {start: 0}, {}
    while queue:
        _, _, _, g, current = heapq.heappop(queue)
        if g != best.get(current):
            continue  # 忽略已被更优路径替代的队列项
        stats.nodes += 1
        if current == goal:
            path = [goal]
            while path[-1] != start:
                path.append(parent[path[-1]])
            return path[::-1], int(g) if float(g).is_integer() else g, stats
        for dr, dc in DIRS:
            nxt = current[0] + dr, current[1] + dc
            if not valid(nxt):
                continue
            candidate = g + float(grid[nxt[0]][nxt[1]])
            if candidate < best.get(nxt, math.inf):
                best[nxt], parent[nxt] = candidate, current
                heapq.heappush(queue, (candidate + h(nxt), -candidate if prefer_deep else 0,
                                      next(serial), candidate, nxt))
    return [], -1, stats


def maze_path(start, end, grid):
    numeric = [["X" if x == "X" else 1 for x in row] for row in grid]
    return astar(numeric, start, end)[0]


def weighted_cost(start, end, grid):
    numeric = [[0 if x == "E" else 1 if x == "S" else x for x in row] for row in grid]
    return astar(numeric, start, end)[1]


@dataclass
class TreeNode:
    value: int | None = None
    children: list = field(default_factory=list)


def tree_search(root, pruning=True, order="original"):
    if order not in ("original", "reverse"):
        raise ValueError("树搜索顺序必须为 original 或 reverse")
    stats = Stats()
    trace = []

    def visit(node, is_max, alpha, beta, name):
        stats.nodes += 1
        if not node.children:
            if node.value is None:
                raise ValueError("叶子必须有 value")
            stats.leaves += 1
            trace.append((name, node.value))
            return node.value
        children = list(enumerate(node.children))
        if order == "reverse":
            children.reverse()
        value = -math.inf if is_max else math.inf
        for index, (original_i, child) in enumerate(children):
            v = visit(child, not is_max, alpha, beta, f"{name}.{original_i}")
            value = max(value, v) if is_max else min(value, v)
            if is_max:
                alpha = max(alpha, value)
            else:
                beta = min(beta, value)
            if pruning and alpha >= beta and index + 1 < len(children):
                stats.cutoffs += 1
                break
        return value

    return visit(root, True, -math.inf, math.inf, "root"), stats, trace


def sample_tree():
    def pair(a, b):
        return TreeNode(children=[TreeNode(a), TreeNode(b)])
    return TreeNode(children=[TreeNode(children=[pair(3, 5), pair(6, 9)]),
                              TreeNode(children=[pair(6, 9), pair(1, 2)])])


TREASURE_GRID = [
    [1,1,1,"X",2,1,1], [1,"X",6,"X",1,"X",1],
    [1,1,1,1,1,1,1], ["X",1,"X",8,"X",1,"X"],
    [1,1,1,1,1,1,1], [1,"X",9,"X",1,"X",1],
    [1,1,1,"X",1,1,1]]
POSITIONS = {"A": (0,0), "B": (6,6), "T1": (0,6), "T2": (2,2), "T3": (4,4), "T4": (6,0)}
VALUES = {"T1": 9, "T2": 6, "T3": 7, "T4": 7}


def distance_matrix(grid=None, positions=None):
    grid = TREASURE_GRID if grid is None else grid
    positions = POSITIONS if positions is None else positions
    return {a: {b: 0 if a == b else astar(grid, tuple(pa), tuple(pb))[1]
                for b, pb in positions.items()} for a, pa in positions.items()}


@dataclass(frozen=True)
class State:
    a: str = "A"
    b: str = "B"
    remaining: tuple = ("T1", "T2", "T3", "T4")
    score_a: int = 0
    score_b: int = 0
    player: str = "A"


def game_search(distances, depth=4, pruning=True, order="original", state=None, values=None):
    if not isinstance(depth, int) or depth < 0:
        raise ValueError("depth 必须为非负整数")
    if order not in ("original", "reverse", "greedy"):
        raise ValueError("博弈搜索顺序必须为 original、reverse 或 greedy")
    stats = Stats()
    values = VALUES if values is None else values
    state = State() if state is None else state
    if state.player not in ("A", "B"):
        raise ValueError("player 必须为 A 或 B")

    def visit(s, left, alpha, beta):
        stats.nodes += 1
        if left == 0 or not s.remaining:
            stats.leaves += 1
            return s.score_a - s.score_b, None, []
        maximizing = s.player == "A"
        pos = s.a if maximizing else s.b
        targets = [t for t in s.remaining if distances[pos][t] >= 0]
        if order == "reverse":
            targets.reverse()
        elif order == "greedy":
            targets.sort(key=lambda t: (-(values[t]-distances[pos][t]), t))
        if not targets:
            stats.leaves += 1
            return s.score_a-s.score_b, None, []  # 无合法动作，结束当前分支
        best = -math.inf if maximizing else math.inf
        choice, sequence = None, []
        for i, target in enumerate(targets):
            gain = values[target] - distances[pos][target]
            remaining = tuple(t for t in s.remaining if t != target)
            child = (State(target, s.b, remaining, s.score_a+gain, s.score_b, "B") if maximizing
                     else State(s.a, target, remaining, s.score_a, s.score_b+gain, "A"))
            v, _, seq = visit(child, left-1, alpha, beta)
            if choice is None or (v > best if maximizing else v < best):
                best, choice, sequence = v, target, [target]+seq
            if maximizing:
                alpha = max(alpha, best)
            else:
                beta = min(beta, best)
            if pruning and alpha >= beta and i+1 < len(targets):
                stats.cutoffs += 1
                break
        return best, choice, sequence

    value, target, sequence = visit(state, depth, -math.inf, math.inf)
    return {"best_target": target, "best_value": value, "sequence": sequence}, stats
