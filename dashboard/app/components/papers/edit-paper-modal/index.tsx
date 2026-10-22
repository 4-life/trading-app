import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFetcher } from 'react-router';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { FIELD_CLASS } from '@/lib/styles';
import { AVERAGING_KINDS } from '@/constants/papers';
import type { ActionResult } from '@/types/action';
import type { Paper } from '@/types/paper';

import { PaperExitsFields } from '../paper-exits-fields';
import { PositionManagementFields } from '../position-management-fields';
import { SweepPanel } from './sweep-panel';

// Edits the leverage (only without an open position) and, for an averaging
// paper, its position management (at once, an open position included) -
// docs/papers.md#editing.
export function EditPaperDialog({ paper }: { paper: Paper }) {
  const fetcher = useFetcher<ActionResult>();
  const [open, setOpen] = useState(false);
  // Closes once the save went through; an error keeps it open, shown in it.
  useEffect(() => {
    if (fetcher.state === 'idle' && fetcher.data && !fetcher.data.error) {
      setOpen(false);
    }
  }, [fetcher.state, fetcher.data]);
  // Averaging and single papers can sweep their settings (Find best params).
  const sweepable = AVERAGING_KINDS.includes(paper.kind) || paper.kind === 'single';
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="xs" variant="outline" />}>
        Edit
      </DialogTrigger>
      <DialogContent
        className={
          sweepable ? 'sm:max-w-3xl' : undefined
        }
      >
        <DialogHeader>
          <DialogTitle>{`Edit paper ${String(paper.id)}`}</DialogTitle>
          <DialogDescription>
            {`${paper.executor} on ${paper.asset}.`}
          </DialogDescription>
        </DialogHeader>
        <fetcher.Form method="post" className="space-y-3">
          <input type="hidden" name="intent" value="updatePaper" />
          <input type="hidden" name="paperId" value={paper.id} />
          <label className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            Leverage
            <input
              name="leverage"
              type="number"
              step="0.1"
              min="0.1"
              defaultValue={Number(paper.leverage)}
              className={`${FIELD_CLASS} w-28`}
            />
          </label>
          {AVERAGING_KINDS.includes(paper.kind) && (
            <PositionManagementFields paper={paper} />
          )}
          {paper.kind === 'single' && <PaperExitsFields paper={paper} />}
          {fetcher.data?.error && (
            <p className="text-sm text-destructive">{fetcher.data.error}</p>
          )}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              Cancel
            </DialogClose>
            <Button type="submit" disabled={fetcher.state !== 'idle'}>
              {fetcher.state === 'idle' ? (
                'Save'
              ) : (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  {AVERAGING_KINDS.includes(paper.kind)
                    ? 'Saving, backtesting…'
                    : 'Saving…'}
                </>
              )}
            </Button>
          </DialogFooter>
        </fetcher.Form>
        {sweepable && <SweepPanel paper={paper} />}
      </DialogContent>
    </Dialog>
  );
}
