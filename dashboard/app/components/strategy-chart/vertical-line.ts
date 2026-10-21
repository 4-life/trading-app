// A dashed vertical line across the whole pane at one candle - a liquidated
// averaging backtest position. Built like ./segment.ts.
import type {
  Coordinate,
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

const WIDTH_PX = 1;
const DASH_PX = [6, 4];

class VerticalLinePaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly x: Coordinate | null,
    private readonly color: string,
  ) {}

  draw(target: Target) {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      if (this.x === null) return;
      context.strokeStyle = this.color;
      context.lineWidth = WIDTH_PX;
      context.setLineDash(DASH_PX);
      context.beginPath();
      context.moveTo(this.x, 0);
      context.lineTo(this.x, mediaSize.height);
      context.stroke();
    });
  }
}

class VerticalLinePaneView implements IPrimitivePaneView {
  private x: Coordinate | null = null;

  constructor(private readonly source: VerticalLine) {}

  update() {
    const { chart } = this.source;
    if (!chart) return;
    this.x = chart.timeScale().timeToCoordinate(this.source.time);
  }

  renderer() {
    return new VerticalLinePaneRenderer(this.x, this.source.color);
  }
}

export class VerticalLine implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null;
  private readonly views = [new VerticalLinePaneView(this)];

  constructor(
    readonly time: Time,
    readonly color: string,
  ) {}

  attached({ chart }: SeriesAttachedParameter<Time>) {
    this.chart = chart as IChartApi;
  }

  detached() {
    this.chart = null;
  }

  updateAllViews() {
    this.views.forEach((v) => v.update());
  }

  paneViews() {
    return this.views;
  }
}
