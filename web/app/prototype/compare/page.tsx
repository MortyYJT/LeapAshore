import { Comparison } from '../../../components/prototype/catalog';
import { masterPrograms, sampleRequirements } from '../../../lib/prototype-library-server';
import { singleQuery } from '../../../lib/prototype-library';
export default async function Page({searchParams}: {searchParams: Promise<Record<string,string|string[]|undefined>>}) {
  const query = singleQuery(await searchParams);
  const codes = [...new Set((query.codes || '').split(','))];
  const selected = codes.map(code => masterPrograms.find(p => p.code === code)).filter(p => p !== undefined).map(program => ({program, rules:sampleRequirements(program.code)}));
  return <Comparison selected={selected}/>;
}
