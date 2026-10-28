import AdvisorView from '../../../components/AdvisorView';
import { Heading } from '../../../components/prototype/shared';
export default function Page() { return <><Heading title="和顾问聊聊你的疑问">由 LangGraph agent 实时回答：先判断意图，问官方要求时只引用已收录的官方来源，修改选校组合前会请你确认。</Heading><AdvisorView/></>; }
