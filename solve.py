"""四题输入输出入口：python solve.py maze --input examples/maze.json。"""
import argparse
import json
from pathlib import Path
from algorithms import TreeNode, State, maze_path, weighted_cost, tree_search, distance_matrix, game_search


def read_tree(obj, is_max=True):
    if "is_maximizing_player" in obj and obj["is_maximizing_player"] != is_max:
        raise ValueError("根须为MAX，后续MAX/MIN应逐层交替")
    children=obj.get("children") or []
    if children:
        return TreeNode(children=[read_tree(c,not is_max) for c in children])
    value=obj.get("value")
    if not isinstance(value,(int,float)):
        raise ValueError("叶子 value 必须为数值")
    return TreeNode(value=value)


def solve(task,payload):
    if task=="maze":
        return maze_path(tuple(payload["start"]),tuple(payload["end"]),payload["grid"])
    if task=="weighted":
        return weighted_cost(tuple(payload["start"]),tuple(payload["end"]),payload["grid"])
    if task=="tree":
        root=read_tree(payload.get("tree_structure",payload))
        return tree_search(root)[0]
    if task=="treasure":
        values=payload.get("values")
        dist=distance_matrix(payload.get("grid"),payload.get("positions"))
        state=State(remaining=tuple(values)) if values is not None else State()
        result,_=game_search(dist,payload.get("H",4),state=state,values=values)
        return {k:result[k] for k in ("best_target","best_value")}
    raise ValueError("未知题目")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task",choices=("maze","weighted","tree","treasure"))
    parser.add_argument("--input",type=Path,required=True)
    args=parser.parse_args()
    payload=json.loads(args.input.read_text(encoding="utf-8-sig"))
    print(json.dumps(solve(args.task,payload),ensure_ascii=False))


if __name__=="__main__":
    main()
