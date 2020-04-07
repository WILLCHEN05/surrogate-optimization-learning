FILENAME='2020-0405-stochastic-server'

NODES=60
NOISE=0.0
BUDGET=2
PROB=0.2
CUTSIZE='0.5n'
SELECTION='coverage'

python3 exp1.py --filename=$FILENAME --number-nodes=$NODES --noise=$NOISE --budget=$BUDGET --prob=$PROB --cut-size=$CUTSIZE --block-selection=$SELECTION
