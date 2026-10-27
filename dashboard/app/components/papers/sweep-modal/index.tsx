import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import type { Paper } from '@/types/paper';

import { SweepPanel } from './sweep-panel';

// A paper's settings sweep, "Find best params" (docs/api.md) - averaging and
// single papers only (isSweepable).
export function SweepDialog({ paper }: { paper: Paper }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button size="xs" variant="outline" />}>
        Sweep
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{`Sweep paper ${String(paper.id)}`}</DialogTitle>
          <DialogDescription>
            {`${paper.executor} on ${paper.asset}.`}
          </DialogDescription>
        </DialogHeader>
        <SweepPanel paper={paper} />
      </DialogContent>
    </Dialog>
  );
}

export const isSweepable = (paper: Paper) =>
  paper.kind === 'averaging' || paper.kind === 'single';
