import { notFound } from 'next/navigation';
import { courses } from '../../../../prototype-fixtures/data';
import { Heading, Attribution, CourseCard } from '../../../../components/prototype/shared';
import ChineseRules from '../../../../components/prototype/chinese-rules';
export default async function Page({ params }: { params: Promise<{ provider: string }> }) { const { provider } = await params; const list = courses.filter(c => c['CRICOS Provider Code'] === provider); if (!list.length) notFound(); return <><Heading title={list[0]['Institution Name']}>CRICOS 院校编码 {provider}<Attribution/></Heading><h2 className="mb-4 text-lg font-semibold">本原型收录的项目</h2><div className="grid gap-5 md:grid-cols-2">{list.map(c => <CourseCard key={c['CRICOS Course Code']} course={c}/>)}</div><ChineseRules/></>; }
