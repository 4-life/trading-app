// A solid line through time x price points on a series - one per averaging
// hedge position (its average entry as steps), so positions never join each
// other the way the points of one line series do. Built like ./segment.ts.
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

class PathPaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly points: ViewPoint[],
    private readonly color: string,
  ) {}

  draw(target: Target) {
    target.useMediaCoordinateSpace(({ context }) => {
      context.strokeStyle = this.color;
      context.lineWidth = WIDTH_PX;
      context.setLineDash([]);
      context.beginPath();
      let drawing = false;
      for (const { x, y } of this.points) {
        // A point off the loaded candles breaks the line there.
        if (x === null || y === null) {
          drawing = false;
          continue;
        }
        if (drawing) {
          context.lineTo(x, y);
        } else {
          context.moveTo(x, y);
          drawing = true;
        }
      }
      context.stroke();
    });
  }
}

class PathPaneView implements IPrimitivePaneView {
  private points: ViewPoint[] = [];

  constructor(private readonly source: Path) {}

  update() {
    const { series, chart } = this.source;
    if (!series || !chart) return;
    const timeScale = chart.timeScale();
    this.points = this.source.points.map((p) => ({
      x: timeScale.timeToCoordinate(p.time),
      y: series.priceToCoordinate(p.price),
    }));
  }

  renderer() {
    return new PathPaneRenderer(this.points, this.source.color);
  }
}

export class Path implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  private readonly views = [new PathPaneView(this)];

  constructor(
    readonly points: Point[],
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
