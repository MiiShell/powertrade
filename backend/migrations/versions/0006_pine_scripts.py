"""pine scripts (user indicators, executed client-side in a sandboxed web worker)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Scripts are stored verbatim (multi-line strings).
OBV_RSI = r"""//@version=5
// Ported from Pine v4 (original: [Hoss] OBV RSI-pincescript.md) to v5 for PineTS.
indicator(title="[Hoss] OBV RSI")
obvsrc = close
change_1 = ta.change(obvsrc)
// PineTS: compute the signed volume outside ta.cum() (inline ta-calls inside ternaries are mis-evaluated)
obv_vol = change_1 > 0 ? volume : change_1 < 0 ? -volume : 0 * volume
obv = ta.cum(obv_vol)

src = obv
len = input.int(5, minval=1, title="RSI Length", group="Strategy Modification")
src_chg = ta.change(src)
up = ta.rma(math.max(src_chg, 0), len)
down = ta.rma(-math.min(src_chg, 0), len)
rsi = down == 0 ? 100 : up == 0 ? 0 : 100 - 100 / (1 + up / down)
higherlvl = input.int(70, title="Higher Level", group="Strategy Modification")
lowerlvl = input.int(30, title="Lower Level", group="Strategy Modification")

plot_color = rsi >= higherlvl ? color.red : rsi <= lowerlvl ? color.green : color.new(#b7b7b7, 60)
plot(rsi, color=plot_color, title="OBV RSI")

band1 = hline(higherlvl, color=color.new(#ff6f6f, 61))
band0 = hline(lowerlvl, color=color.new(#006600, 50))

table_visible = input.bool(false, title="Show Table", group="RSI Cross Monitor")
table_length = input.int(300, title="Table Lookback Length", group="RSI Cross Monitor")

count_occurrences(cond, length) =>
    count = 0
    for i = 0 to length - 1
        if cond[i]
            count := count + 1
    count

cross_above_higher = ta.crossover(rsi, higherlvl)
cross_below_lower = ta.crossunder(rsi, lowerlvl)
above_higher_count = count_occurrences(cross_above_higher, table_length)
below_lower_count = count_occurrences(cross_below_lower, table_length)

if (table_visible)
    var table tbl = table.new(position=position.bottom_right, rows=2, columns=2)
    if (barstate.islast)
        table.cell(tbl, 0, 0, "Higher Level Cross", bgcolor=color.gray, text_color=color.white)
        table.cell(tbl, 0, 1, "Lower Level Cross", bgcolor=color.gray, text_color=color.white)
        table.cell(tbl, 1, 0, str.tostring(above_higher_count), bgcolor=color.new(color.red, 90), text_color=color.red)
        table.cell(tbl, 1, 1, str.tostring(below_lower_count), bgcolor=color.new(color.green, 90), text_color=color.green)
"""

VWAP_DEV = r"""//@version=5
// Original: [Hoss] VWAP AD-pincescript.md. Adapted for PineTS: `type` renamed, if-expression -> ternary.
indicator('[Hoss] VWAP Deviation', overlay=true)

ls = input(false, title='Log-space', group = "Optional")
devType = 'Average Deviation'
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
dev = devType == 'Standard Deviation' ? pine_vwstdev(src, length, vwmean) : pine_vwavdev(src, length, vwmean)


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
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pine_script (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name        text NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 80),
            source      text NOT NULL CHECK (length(source) <= 100000),
            builtin     boolean NOT NULL DEFAULT false,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    t = sa.table(
        "pine_script",
        sa.column("name", sa.Text),
        sa.column("source", sa.Text),
        sa.column("builtin", sa.Boolean),
    )
    op.bulk_insert(
        t,
        [
            {"name": "[Hoss] OBV RSI", "source": OBV_RSI, "builtin": True},
            {"name": "[Hoss] VWAP Deviation", "source": VWAP_DEV, "builtin": True},
        ],
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pine_script")
