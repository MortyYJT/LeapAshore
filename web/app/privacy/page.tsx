import type { Metadata } from "next";
import Link from "next/link";

import { Notice } from "@/components/ui";

export const metadata: Metadata = { title: "隐私政策 · 鱼跃彼岸" };

/**
 * The privacy policy (openspec account-login, spec privacy-policy). Drafted by Claude on 2026-10-30 from
 * what the code actually stores and sends; MortyYJT has to review it before login mode is switched on.
 */
export default function PrivacyPage() {
  return (
    <main className="page privacy">
      <div className="title-row">
        <div>
          <h1>隐私政策</h1>
          <p className="lede">鱼跃彼岸是 MortyYJT 的个人项目。这里说明它收集什么、为什么、交给谁处理、存多久、怎么删除。</p>
        </div>
      </div>
      <div className="section">
        <Notice>草稿：由 AI 按代码实际行为起草（2026-10-30），等待 MortyYJT 审核，审核前不作为正式承诺。</Notice>
      </div>

      <section className="panel panel-pad section">
        <h2>收集哪些信息</h2>
        <ul>
          <li>
            <b>邮箱地址</b>：用于登录。登录时我们向这个邮箱发送 6 位验证码，并记录发送时间、尝试次数和请求来源 IP，用来限制发送频率、防止猜验证码。
          </li>
          <li>
            <b>你填写的背景</b>：本科院校、专业、均分和分制、英语成绩、申请学位和方向、入学时间、每年预算。用于按官方要求给项目分档、排路线图。
          </li>
          <li>
            <b>选校组合和路线图</b>：你加入的项目、档位、首选、申请状态，以及路线图任务的完成情况和修改记录。
          </li>
          <li>
            <b>上传的材料</b>：成绩单、简历等文件本身，以及文件名、类型、大小和版本。
          </li>
          <li>
            <b>和顾问的对话</b>：你发给顾问的消息和它的回答。对话目前只保存在服务器内存里，服务重启后清空。为了限制使用频率和每日用量，服务器按账号（未登录时按匿名标识）和请求来源 IP 记录每次提问的时间和消耗的模型用量（token 数），不记录内容。
          </li>
          <li>
            <b>登录会话</b>：登录成功后，浏览器保存一个名为 <code>leapashore_session</code> 的 Cookie（仅服务器可读），服务器保存它的摘要、创建时间、IP 和浏览器标识，有效期 30 天。未登录时用过的网站会在浏览器保存匿名标识 <code>leapashore_client</code>。
          </li>
        </ul>
        <p>我们不收集姓名、电话、身份证号，也不使用第三方统计或广告追踪。</p>
      </section>

      <section className="panel panel-pad section">
        <h2>交给谁处理</h2>
        <ul>
          <li>
            <b>腾讯云</b>：网站和数据库运行在腾讯云中国香港地域的服务器上；验证码邮件通过腾讯云邮件推送（SES）发出，腾讯云会处理你的邮箱地址和邮件内容。
          </li>
          <li>
            <b>DeepSeek（深度求索）</b>：你发给顾问的消息，以及顾问为回答而读取的你的背景和选校组合，会发送给 DeepSeek 的模型接口生成回答。
          </li>
        </ul>
        <p>除此之外，我们不向任何人出售、出租或提供你的信息。</p>
      </section>

      <section className="panel panel-pad section">
        <h2>存多久</h2>
        <ul>
          <li>账号和它的全部数据：保存到你注销账号为止。</li>
          <li>未登录时留下的匿名数据：第一次登录时并入你的账号；没人认领的，最后一次使用 90 天后删除。</li>
          <li>验证码记录：2 天后删除。过期的登录会话会被定期清理。</li>
          <li>顾问的限流记录：提问时间在限流窗口过后自动删除（按默认设置最长约 2 小时），每日用量 2 天后自动删除。</li>
        </ul>
      </section>

      <section className="panel panel-pad section">
        <h2>怎么删除</h2>
        <p>
          登录后在<Link href="/me">「我的」</Link>页面点「注销账号」，输入登录邮箱确认。注销会立即删除这个账号的背景、选校组合、路线图、上传的材料文件、修改记录、登录会话和验证码记录，不能恢复。
        </p>
        <p>退出登录只结束当前会话，不删除数据。</p>
      </section>

      <section className="panel panel-pad section">
        <h2>联系我们</h2>
        <p>联系方式待 MortyYJT 补充。</p>
      </section>
    </main>
  );
}
