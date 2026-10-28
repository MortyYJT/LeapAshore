import { AssessmentResult } from '../../../../components/prototype/assessment';
import { masterPrograms, sampleRequirements } from '../../../../lib/prototype-library-server';
export default function Page() { return <AssessmentResult skipped={masterPrograms.filter(p => !sampleRequirements(p.code)).length}/>; }
