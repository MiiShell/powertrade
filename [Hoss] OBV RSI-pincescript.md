//@version=4
study(title="[Hoss] OBV RSI")
obvsrc = close
change_1 = change(obvsrc)
obv = cum(change(obvsrc) > 0 ? volume : change_1 < 0 ? -volume : 0 * volume)

src = obv
len = input(5, minval=1, title="RSI Length", group="Strategy Modification")
up = rma(max(change(src), 0), len)
down = rma(-min(change(src), 0), len)
rsi = down == 0 ? 100 : up == 0 ? 0 : 100 - 100 / (1 + up / down)
higherlvl = input(70, title="Higher Level", group="Strategy Modification")
lowerlvl = input(30, title="Lower Level", group="Strategy Modification")


plot_color = rsi >= higherlvl ? color.red : rsi <= lowerlvl ? color.green : color.new(#b7b7b7, 60)
plot(rsi, color=plot_color)

//plot(rsi, color=color.white)

band1 = hline(higherlvl, color=color.new(#ff6f6f, 61))
band0 = hline(lowerlvl, color=color.new(#006600, 50))

// Input to enable or disable the table visibility
table_visible = input(false, title="Show Table", group="RSI Cross Monitor")
// Input for the number of candles to look back
table_length = input(300, title="Table Lookback Length", group="RSI Cross Monitor")

// Custom count function
count_occurrences(cond, length) =>
    count = 0
    for i = 0 to length - 1
        if cond[i]
            count := count + 1
    count

// Count occurrences of RSI crossing higher level and lower level
cross_above_higher = crossover(rsi, higherlvl)
cross_below_lower = crossunder(rsi, lowerlvl)
above_higher_count = count_occurrences(cross_above_higher, table_length)
below_lower_count = count_occurrences(cross_below_lower, table_length)

// Create table in the bottom right corner
if (table_visible)
    var table tbl = table.new(position=position.bottom_right, rows=2, columns=2)
    if (barstate.islast)
        // Update the table headers
        table.cell(tbl, 0, 0, "Higher Level Cross", bgcolor=color.gray, text_color=color.white)
        table.cell(tbl, 0, 1, "Lower Level Cross", bgcolor=color.gray, text_color=color.white)
        
        // Update the table values
        table.cell(tbl, 1, 0, tostring(above_higher_count), bgcolor=color.new(color.red, 90), text_color=color.red)
        table.cell(tbl, 1, 1, tostring(below_lower_count), bgcolor=color.new(color.green, 90), text_color=color.green)