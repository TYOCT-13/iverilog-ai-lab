# traffic_light_emergency 规格

四状态循环为主路绿、主路黄、支路绿、支路黄，每个时钟沿前进一状态。`rst_n` 为低有效异步复位，复位后主路绿。`emergency=1` 时立即输出主路黄、支路红，并在下一个时钟进入主路黄；解除后继续正常循环。任何非法状态恢复到主路绿。灯值：红=`00`、黄=`01`、绿=`10`。

时序图源：`waveforms/traffic_light_emergency.json5`。
