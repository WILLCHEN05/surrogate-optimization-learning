FILENAME='1005-server'

NODES=60
NOISE=0.0
BUDGET=2
PROB=0.2

python3 generate_fig4.py --filename=$FILENAME --number-nodes=$NODES --noise=$NOISE --budget=$BUDGET --prob=$PROB
