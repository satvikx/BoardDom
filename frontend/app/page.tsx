import { HomeActions } from "@/components/HomeActions";
export default function Home() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">For the work behind the lesson</p>
        <h1>
          Clear your desk.
          <br />
          <em>Make room to teach.</em>
        </h1>
        <p className="hero-copy">
          Give every lesson a home. Organize your ideas, gather your source
          materials, and pick up right where you left off.
        </p>
        <HomeActions />
      </section>
      <section className="feature-grid" aria-label="What you can do">
        <article>
          <span className="feature-number">01 / PLAN</span>
          <h2>A space for each lesson</h2>
          <p>
            Set your subject, learner level, and lesson length. Keep the details
            in one place.
          </p>
        </article>
        <article>
          <span className="feature-number">02 / GATHER</span>
          <h2>Bring your materials</h2>
          <p>
            Upload PDFs, Markdown, and text notes. Your original files stay
            ready to download.
          </p>
        </article>
        <article>
          <span className="feature-number">03 / RETURN</span>
          <h2>Pick up where you left off</h2>
          <p>
            Saved workspaces and sources, waiting for you when the next idea
            comes.
          </p>
        </article>
      </section>
    </>
  );
}
