import Link from "next/link";
export default function NotFound() {
  return (
    <section className="panel empty">
      <h1>페이지를 찾을 수 없어요</h1>
      <p>주소를 확인하거나 운영 현황으로 이동해 주세요.</p>
      <Link className="button section-gap" href="/">
        운영 현황
      </Link>
    </section>
  );
}
