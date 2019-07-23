FILENAME="0722-test"
BUDGET=2
NODES=20
SEED=1
METHOD=1
MINCUT=1

python3 pathProbabilities.py --epochs=50 --fixed-graph=0 --method=$METHOD --seed=$SEED --filename=$FILENAME --budget=$BUDGET --distribution=1 --number-nodes=$NODES --number-graphs=1 --number-samples=20 --learning-rate=0.01 --prob=0.3 --feature-size=5 --number-sources=2 --number-targets=2 --mincut=$MINCUT
