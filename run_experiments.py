"""运行全部题目、对照实验及正确性测试，结果保存在 results/。"""
from pathlib import Path
import csv
import json
import platform
import random
import heapq
import statistics
from time import perf_counter_ns
from dataclasses import asdict
from algorithms import (DIRS, TreeNode, State, VALUES, POSITIONS, TREASURE_GRID,
                        astar, maze_path, weighted_cost, tree_search, sample_tree,
                        distance_matrix, game_search)

ROOT = Path(__file__).resolve().parent
MAZE = [list(r) for r in ['S..X.', '.X...', '.X.X.', '...XE', 'XX...']]
WEIGHTED = [['S',1,1,8,1],[1,8,3,1,1],[1,8,1,8,1],[1,1,1,8,1],[8,8,1,1,'E']]


def timed(fn, repeats=31):
    for _ in range(5):
        fn()  # 预热不计时，降低首次运行对小样例的影响
    times=[]
    result=None
    for _ in range(repeats):
        t=perf_counter_ns()
        result=fn()
        times.append((perf_counter_ns()-t)/1000)
    return result, round(statistics.median(times), 3)


def reference_distance(grid, start, goal):
    # 独立 Dijkstra，不调用 A*，用于随机正确性对照。
    q=[(0,start)]
    seen={}
    while q:
        cost,p=heapq.heappop(q)
        if p in seen: continue
        seen[p]=cost
        if p==goal: return cost
        for dr,dc in DIRS:
            r,c=p[0]+dr,p[1]+dc
            if 0<=r<len(grid) and 0<=c<len(grid[0]) and grid[r][c]!='X' and (r,c) not in seen:
                heapq.heappush(q,(cost+grid[r][c],(r,c)))
    return -1


def self_tests():
    rng=random.Random(42)
    for i in range(250):
        grid=[[('X' if rng.random()<0.25 else rng.randint(1,9)) for _ in range(6)] for _ in range(6)]
        grid[0][0]=1
        grid[5][5]=i%2  # 同时检验终点0与1
        if i%3==0:
            grid[2][3]=0  # 同时覆盖中间零代价格子的回退逻辑
        ref=reference_distance(grid,(0,0),(5,5))
        for heuristic in ('zero','manhattan'):
            for deep in (False,True):
                path,cost,_=astar(grid,(0,0),(5,5),heuristic,deep)
                assert cost==ref
                if path:
                    assert path[0]==(0,0) and path[-1]==(5,5)
                    assert all(abs(a[0]-b[0])+abs(a[1]-b[1])==1 for a,b in zip(path,path[1:]))
                    assert sum(grid[r][c] for r,c in path[1:])==cost
    for _ in range(100):
        def tree(d):
            return TreeNode(rng.randint(-20,20)) if d==0 else TreeNode(children=[tree(d-1) for _ in range(rng.randint(1,3))])
        root=tree(4)
        baseline=tree_search(root,False)[0]
        assert tree_search(root,True)[0]==baseline==tree_search(root,True,'reverse')[0]
    dist=distance_matrix()
    for a,pa in POSITIONS.items():
        for b,pb in POSITIONS.items():
            assert dist[a][b]==reference_distance(TREASURE_GRID,pa,pb)
    for _ in range(100):
        vals={t:rng.randint(-5,15) for t in VALUES}
        for depth in (2,4):
            baseline=game_search(dist,depth,False,values=vals)[0]['best_value']
            for order in ('original','reverse','greedy'):
                assert game_search(dist,depth,True,order,values=vals)[0]['best_value']==baseline
    # 独立小规模穷举：不调用 game_search，不使用 State 状态转移。
    def oracle(a,b,remaining,turn,depth,values):
        if depth==0 or not remaining:
            return 0,set()
        scores={}
        for t in remaining:
            if turn=='A':
                future=oracle(t,b,tuple(x for x in remaining if x!=t),'B',depth-1,values)[0]
                scores[t]=values[t]-dist[a][t]+future
            else:
                future=oracle(a,t,tuple(x for x in remaining if x!=t),'A',depth-1,values)[0]
                scores[t]=-(values[t]-dist[b][t])+future
        value=(max if turn=='A' else min)(scores.values())
        return value,{t for t,v in scores.items() if v==value}
    for i in range(100):
        remaining=tuple(rng.sample(list(VALUES),rng.randint(1,4)))
        state=State(rng.choice(list(dist)),rng.choice(list(dist)),remaining,
                    rng.randint(-10,10),rng.randint(-10,10),rng.choice(['A','B']))
        values={t:rng.randint(-10,20) for t in VALUES}
        depth=rng.randint(1,4)
        expected,actions=oracle(state.a,state.b,remaining,state.player,depth,values)
        expected+=state.score_a-state.score_b
        for order in ('original','reverse','greedy'):
            answer,_=game_search(dist,depth,True,order,state,values)
            assert answer['best_value']==expected and answer['best_target'] in actions
    assert maze_path((0,0),(0,2),[['S','X','E']])==[]
    assert weighted_cost((0,0),(0,2),[['S','X','E']])==-1
    assert maze_path((0,0),(0,0),[['S']])==[(0,0)]
    assert weighted_cost((0,0),(0,1),[['S','E']])==0
    bad_calls=[lambda:astar([[1]],(0,0),(0,0),'typo'),
               lambda:astar([[1,-1]],(0,0),(0,1)),
               lambda:astar([[1],[1,2]],(0,0),(1,0)),
               lambda:game_search(dist,-1),lambda:tree_search(sample_tree(),order='typo')]
    for fn in bad_calls:
        try:
            fn()
        except ValueError:
            pass
        else:
            raise AssertionError('非法输入应明确报错')
    from solve import solve
    for task,filename,expected in [('maze','maze.json',maze_path((0,0),(3,4),MAZE)),
                                   ('weighted','weighted.json',7),('tree','tree.json',5),
                                   ('treasure','treasure_h2.json',{'best_target':'T2','best_value':-1}),
                                   ('treasure','treasure_h4.json',{'best_target':'T3','best_value':3})]:
        payload=json.loads((ROOT/'examples'/filename).read_text(encoding='utf-8'))
        actual=solve(task,payload)
        # JSON 将坐标元组表示为数组，统一后比较。
        assert json.dumps(actual)==json.dumps(expected)
    return {'random_path_cases':250,'random_tree_cases':100,'random_game_value_sets':100,
            'path_configurations_per_map':4,'matrix_reference_checks':36,
            'independent_game_states':100,'invalid_input_cases':5,'interface_examples':5,
            'boundary_cases':4,'status':'passed'}


def main():
    out=ROOT/'results'
    out.mkdir(exist_ok=True)
    results={'environment':{'python':platform.python_version(),'platform':platform.platform(),
                            'timing':'5 warmups + 31 repetitions, median microseconds, no file I/O'},
             'tests':self_tests()}
    maze_numeric=[['X' if x=='X' else 1 for x in r] for r in MAZE]
    weighted_numeric=[[0 if x=='E' else 1 if x=='S' else x for x in r] for r in WEIGHTED]
    search_rows=[]
    for name,grid,start,end in [('maze',maze_numeric,(0,0),(3,4)),('weighted',weighted_numeric,(0,0),(4,4)),
                               ('open_40',[[1]*40 for _ in range(40)],(0,0),(39,39))]:
        for heuristic,deep in [('zero',False),('manhattan',False),('manhattan',True)]:
            (path,cost,stats),us=timed(lambda:astar(grid,start,end,heuristic,deep))
            search_rows.append({'case':name,'heuristic':heuristic,'prefer_deep':deep,'cost':cost,
                                'nodes':stats.nodes,'median_us':us})
            if name in ('maze','weighted') and heuristic=='manhattan' and not deep:
                results[name]={'path':path,'cost':cost,'enter_costs':[grid[r][c] for r,c in path[1:]]}
    assert results['maze']['cost']==7 and results['weighted']['cost']==7
    tree_rows=[]
    for order in ('original','reverse'):
        for pruning in (False,True):
            (value,stats,trace),us=timed(lambda:tree_search(sample_tree(),pruning,order))
            assert value==5
            tree_rows.append({'order':order,'algorithm':'Alpha-beta' if pruning else 'Minimax',
                              'value':value,**asdict(stats),'median_us':us,'trace':trace})
    distances=distance_matrix()
    results['distances']=distances
    game_rows=[]
    for depth in (2,4):
        for order in ('original','reverse','greedy'):
            for pruning in (False,True):
                (answer,stats),us=timed(lambda:game_search(distances,depth,pruning,order))
                assert answer['best_value']==(-1 if depth==2 else 3)
                assert answer['best_target']==('T2' if depth==2 else 'T3')
                game_rows.append({'depth':depth,'order':order,'algorithm':'Alpha-beta' if pruning else 'Minimax',
                                  **answer,**asdict(stats),'median_us':us})
    results.update(search=search_rows,tree=tree_rows,game=game_rows)
    root_values={}
    for depth in (2,4):
        root_values[str(depth)]={}
        for t in VALUES:
            s=State(t,'B',tuple(x for x in VALUES if x!=t),VALUES[t]-distances['A'][t],0,'B')
            root_values[str(depth)][t]=game_search(distances,depth-1,False,state=s)[0]['best_value']
    results['root_values']=root_values
    trap=[[1,1,9,1,1],[1,1,1,1,1]]
    path,cost,stats=astar(trap,(0,0),(0,4))
    assert cost==6 and len(path)-1==6
    results['weighted_detour']={'grid':trap,'path':path,'steps':len(path)-1,'cost':cost,
                                'direct_path_steps':4,'direct_path_cost':12}
    # 固定地图的一次性距离预计算，供所有游戏搜索分支复用。
    (_,matrix_us)=timed(distance_matrix)
    results['matrix_median_us']=matrix_us
    for name,records in [('search',search_rows),('tree',tree_rows),('game',game_rows)]:
        with (out/f'{name}.csv').open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]))
            writer.writeheader(); writer.writerows(records)
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
