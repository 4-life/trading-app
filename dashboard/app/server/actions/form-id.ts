// A record id from a form, digits only - anything else becomes 0 (the API
// answers 404), so a crafted value can't reach another API route through the path.
export function formId(form: FormData, name: string): string {
  const value = String(form.get(name) ?? "");
  return /^\d+$/.test(value) ? value : "0";
}
