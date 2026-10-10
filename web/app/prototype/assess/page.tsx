import { AssessmentForm } from '../../../components/prototype/assessment';
import { chineseSources } from '../../../lib/prototype-library-server';
import { findInstitutions } from './institution-search';
export default async function Page() { return <AssessmentForm institutions={await findInstitutions('')} sources={chineseSources}/>; }
