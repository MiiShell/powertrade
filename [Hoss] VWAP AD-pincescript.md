//@version=5
indicator('[Hoss] VWAP Deviation', overlay=true)

ls = input(false, title='Log-space', group = "Optional")
type = 'Average Deviation'
length = input(60, group="Strategy Modification")
source = input(close, group="Strategy Modification")
_low = ls == true ? math.log(low) : low
_high = ls == true ? math.log(high) : high
src = ls == true ? math.log(source) : source

//weighted mean
pine_vwmean(x, y) =>
    cw = 0
    cd = 0.0
    w_sum = 0.0
    d_sum = 0.0
    for i = 0 to y - 1 by 1
        cd = x[i]
        cw = volume[i]
        d_sum += cw * cd
        w_sum += cw
        w_sum
    d_sum / w_sum

//weighted standard deviation
pine_vwstdev(x, y, b) =>
    d_sum = 0.0
    w_sum = 0.0
    cd = 0.0
    for i = 0 to y - 1 by 1
        cd = x[i]
        cw = volume[i]
        d_sum += cw * math.pow(cd - b, 2)
        w_sum += cw
        w_sum
    math.sqrt(d_sum / w_sum)

//weighted average deviation
pine_vwavdev(x, y, b) =>
    d_sum = 0.0
    w_sum = 0.0
    cd = 0.0
    for i = 0 to y - 1 by 1
        cd = x[i]
        cw = volume[i]
        d_sum += cw * math.abs(cd - b)
        w_sum += cw
        w_sum
    d_sum / w_sum

vwmean = pine_vwmean(src, length)

//consider using Average Deviation instead of Standard Deviatio if there are values outside of 3rd upper & lower bands within a rolling window
dev = if type == 'Standard Deviation'
    dev = pine_vwstdev(src, length, vwmean)
    dev
else if type == 'Average Deviation'
    dev = pine_vwavdev(src, length, vwmean)
    dev


plot(ls == true ? math.exp(vwmean) : vwmean, color=color.new(#b7b7b7, 60), title='Basis')

fill(plot1=plot(ls == true ? math.exp(vwmean + dev * 2) : vwmean + dev * 2, color=color.new(#B20000, 0), title='Upper dev 2'), plot2=plot(ls == true ? math.exp(vwmean + dev * 3) : vwmean + dev * 3, color=color.new(#FF6666, 0), title='Upper dev 3', display=display.none), color=color.new(#FF4D4D, 80), title='Upper band', transp=0)
fill(plot1=plot(ls == true ? math.exp(vwmean - dev * 3) : vwmean - dev * 3, color=color.new(#00CC00, 0), title='Lower dev 3', display=display.none), plot2=plot(ls == true ? math.exp(vwmean - dev * 2) : vwmean - dev * 2, color=color.new(#008000, 0), title='Lower dev 2'), color=color.new(#006600, 80), title='Lower band', transp=0)


// Input to enable or disable the table visibility
table_visible = input(false, title="Show Table", group="Deviation Cross Monitor")
// Input for the number of candles to look back
table_length = input(300, title="Table Lookback Length", group="Deviation Cross Monitor")

// Custom count function
count_occurrences(cond, length) =>
    count = 0
    for i = 0 to length - 1
        if cond[i]
            count := count + 1
    count

// Count occurrences of prices above Upper dev 2 and below Lower dev 2
upper_dev_2 = vwmean + dev * 2
lower_dev_2 = vwmean - dev * 2
above_upper_dev_2 = count_occurrences(close > upper_dev_2, table_length)
below_lower_dev_2 = count_occurrences(close < lower_dev_2, table_length)

// Create table in the bottom right corner
var table tbl = table.new(position=position.bottom_right, rows=2, columns=2)

if table_visible
    if barstate.islast
        // Update the table headers
        table.cell(tbl, 0, 0, "Above Upper Dev 2", bgcolor=color.gray, text_color=color.white)
        table.cell(tbl, 0, 1, "Below Lower Dev 2", bgcolor=color.gray, text_color=color.white)
        
        // Update the table values
        table.cell(tbl, 1, 0, str.tostring(above_upper_dev_2), bgcolor=color.new(color.green, 90), text_color=color.green)
        table.cell(tbl, 1, 1, str.tostring(below_lower_dev_2), bgcolor=color.new(color.red, 90), text_color=color.red)
else
    table.delete(tbl)