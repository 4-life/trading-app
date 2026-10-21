// A filled time x price rectangle on a series - the drawing part of
// lightweight-charts' Rectangle plugin example (rectangle-drawing-tool.ts:
// RectanglePaneRenderer, RectanglePaneView, Rectangle), without its axis
// labels and drawing tool. Used for the liquidity-swing zones and, with a
// fixed pixel height, the swing levels.
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

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

interface ViewPoint {
  x: Coordinate | null;
  y: Coordinate | null;
}

export interface Point {
  time: Time;
  price: number;
}

// Pixel-aligned start and length of a span in bitmap coordinates (the
// examples' positionsBox helper).
function positionsBox(a: number, b: number, pixelRatio: number) {
  const start = Math.round(Math.min(a, b) * pixelRatio);
  const end = Math.round(Math.max(a, b) * pixelRatio);
  return { position: start, length: Math.max(end - start, 1) };
}

class RectanglePaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly p1: ViewPoint,
    private readonly p2: ViewPoint,
    private readonly fillColor: string,
    private readonly heightPx: number | null,
  ) {}

  draw(target: Target) {
    target.useBitmapCoordinateSpace((scope) => {
      const { p1, p2, heightPx } = this;
      if (p1.x === null || p1.y === null || p2.x === null || p2.y === null) return;
      const h = positionsBox(p1.x, p2.x, scope.horizontalPixelRatio);
      // A fixed height: centred on p1's price, whatever the zoom.
      const v =
        heightPx === null
          ? positionsBox(p1.y, p2.y, scope.verticalPixelRatio)
          : positionsBox(p1.y - heightPx / 2, p1.y + heightPx / 2, scope.verticalPixelRatio);
      scope.context.fillStyle = this.fillColor;
      scope.context.fillRect(h.position, v.position, h.length, v.length);
    });
  }
}

class RectanglePaneView implements IPrimitivePaneView {
  private p1: ViewPoint = { x: null, y: null };
  private p2: ViewPoint = { x: null, y: null };

  constructor(private readonly source: Rectangle) {}

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
    return new RectanglePaneRenderer(
      this.p1,
      this.p2,
      this.source.fillColor,
      this.source.heightPx,
    );
  }

  zOrder() {
    return 'bottom' as const;
  }
}

export class Rectangle implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  private readonly views = [new RectanglePaneView(this)];

  constructor(
    readonly p1: Point,
    readonly p2: Point,
    readonly fillColor: string,
    // CSS pixels: a bar of this height at p1's price instead of p1 -> p2.
    readonly heightPx: number | null = null,
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
