// A dashed straight line between two time x price points on a series - one
// per trade (entry -> exit), so trades never join each other the way points
// of one line series do. Built like ./rectangle.ts.
import type {
  Coordinate,
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';

import type { Point } from './rectangle';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

interface ViewPoint {
  x: Coordinate | null;
  y: Coordinate | null;
}

const WIDTH_PX = 2;
const DASH_PX = [6, 4];

class SegmentPaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly p1: ViewPoint,
    private readonly p2: ViewPoint,
    private readonly color: string,
  ) {}

  draw(target: Target) {
    target.useMediaCoordinateSpace(({ context }) => {
      const { p1, p2 } = this;
      if (p1.x === null || p1.y === null || p2.x === null || p2.y === null) return;
      context.strokeStyle = this.color;
      context.lineWidth = WIDTH_PX;
      context.setLineDash(DASH_PX);
      context.beginPath();
      context.moveTo(p1.x, p1.y);
      context.lineTo(p2.x, p2.y);
      context.stroke();
    });
  }
}

class SegmentPaneView implements IPrimitivePaneView {
  private p1: ViewPoint = { x: null, y: null };
  private p2: ViewPoint = { x: null, y: null };

  constructor(private readonly source: Segment) {}

  update() {
    const { series, chart } = this.source;
    if (!series || !chart) return;
    const timeScale = chart.timeScale();
    this.p1 = {
      x: timeScale.timeToCoordinate(this.source.p1.time),
      y: series.priceToCoordinate(this.source.p1.price),
    };
    this.p2 = {
      x: timeScale.timeToCoordinate(this.source.p2.time),
      y: series.priceToCoordinate(this.source.p2.price),
    };
  }

  renderer() {
    return new SegmentPaneRenderer(this.p1, this.p2, this.source.color);
  }
}

export class Segment implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  private readonly views = [new SegmentPaneView(this)];

  constructor(
    readonly p1: Point,
    readonly p2: Point,
    readonly color: string,
  ) {}

  attached({ chart, series }: SeriesAttachedParameter<Time>) {
    this.chart = chart as IChartApi;
    this.series = series;
  }

  detached() {
    this.chart = null;
    this.series = null;
  }

  updateAllViews() {
    this.views.forEach((v) => v.update());
  }

  paneViews() {
    return this.views;
  }
}
