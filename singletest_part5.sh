# FILENAME="0905-server-var0.1"
# BUDGET=2
# NODES=30
# EPOCHS=101
# PROB=0.2
LR=0.005

echo $NODES
echo $VAR
SEED=$VAR
METHOD=4
python3 blockQP.py --epochs=$EPOCHS --fixed-graph=0 --method=$METHOD --seed=$SEED --filename=$FILENAME --budget=$BUDGET --distribution=1 --number-nodes=$NODES --number-graphs=1 --number-samples=$SAMPLES --learning-rate=$LR --prob=$PROB --feature-size=8 --number-sources=5 --number-targets=2 --noise=$NOISE
