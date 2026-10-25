import { AssetsModal } from "@/components/assets-modal";
import { Section } from "@/components/section";
import type { HomeData } from "@/server/home/loader";

export function AssetsSection({
  assets,
  open,
  onOpenChange,
}: Pick<HomeData, "assets"> & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Section name="assets" data={assets} fallback={null}>
      {(a) => (
        <AssetsModal assets={a} open={open} onOpenChange={onOpenChange} />
      )}
    </Section>
  );
}
