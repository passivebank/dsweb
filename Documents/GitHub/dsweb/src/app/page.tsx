import Link from "next/link";
import { domains } from "@/data/domains";

const stats = [
  { value: "1,200+", label: "Domains Acquired" },
  { value: "8", label: "Years in Market" },
  { value: "$4.2M", label: "Transactions Brokered" },
  { value: "40+", label: "TLDs Managed" },
];

const valueProps = [
  {
    title: "Acquisition",
    tagline: "We get there first.",
    description:
      "Proprietary scoring infrastructure evaluates domains across 40+ signals before they hit the open market. Multi-registrar submission architecture with sub-second execution. By the time you see it listed, we already passed on it — or own it.",
  },
  {
    title: "Brokerage",
    tagline: "Discreet. Decisive. Done.",
    description:
      "Confidential buy-side and sell-side representation for premium domain transactions. Escrow.com settlement standard. We don't do tire-kickers, and neither should you.",
  },
  {
    title: "Advisory",
    tagline: "Strategy, not speculation.",
    description:
      "Domain portfolio consulting for brands, investors, and holding companies. Valuation backed by comparable sales data, traffic signals, and commercial intent — not gut feelings.",
  },
];

const featuredDomains = domains.filter((d) => d.featured);

export default function Home() {
  return (
    <>
      {/* ── Hero ── */}
      <section className="bg-charcoal text-white">
        <div className="max-w-7xl mx-auto px-6 py-28 md:py-36 text-center">
          <p className="text-gold text-sm font-medium tracking-[0.2em] uppercase mb-6">
            Domain Investment &amp; Brokerage
          </p>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight max-w-4xl mx-auto">
            We don&apos;t buy domains.
            <br />
            <span className="text-gold">We acquire assets.</span>
          </h1>
          <p className="mt-8 text-lg md:text-xl text-gray-400 max-w-2xl mx-auto leading-relaxed">
            High-authority domains sourced at expiry, scored by data, and held to a standard most investors
            won&apos;t bother with. That&apos;s the point.
          </p>
          <div className="mt-12 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/portfolio"
              className="bg-gold text-charcoal font-semibold px-8 py-3.5 rounded hover:bg-gold-light transition-colors text-sm tracking-wide"
            >
              View Portfolio
            </Link>
            <Link
              href="/contact"
              className="border border-gold/40 text-gold font-semibold px-8 py-3.5 rounded hover:bg-gold hover:text-charcoal transition-all text-sm tracking-wide"
            >
              Start a Conversation
            </Link>
          </div>
        </div>
      </section>

      {/* ── Stats Bar ── */}
      <section className="bg-surface border-b border-border">
        <div className="max-w-7xl mx-auto px-6 py-14">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            {stats.map((stat) => (
              <div key={stat.label}>
                <p className="text-3xl md:text-4xl font-bold text-gold">
                  {stat.value}
                </p>
                <p className="mt-2 text-sm text-muted tracking-wide">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Manifesto Strip ── */}
      <section className="bg-background border-b border-border">
        <div className="max-w-4xl mx-auto px-6 py-16 text-center">
          <blockquote className="text-xl md:text-2xl text-charcoal font-medium leading-relaxed italic">
            &ldquo;Most domains are noise. We filter for signal — traffic authority, link equity, commercial intent.
            If it doesn&apos;t clear our scoring threshold, it doesn&apos;t exist to us.&rdquo;
          </blockquote>
          <div className="mt-6 w-12 h-0.5 bg-gold mx-auto" />
        </div>
      </section>

      {/* ── Value Props ── */}
      <section className="bg-surface">
        <div className="max-w-7xl mx-auto px-6 py-20">
          <div className="grid md:grid-cols-3 gap-12">
            {valueProps.map((prop) => (
              <div key={prop.title} className="group">
                <div className="w-12 h-0.5 bg-gold mb-6 group-hover:w-20 transition-all duration-300" />
                <h3 className="text-xl font-bold text-charcoal">
                  {prop.title}
                </h3>
                <p className="mt-2 text-gold text-sm font-medium">
                  {prop.tagline}
                </p>
                <p className="mt-4 text-muted leading-relaxed text-sm">
                  {prop.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Featured Domains ── */}
      <section className="bg-background">
        <div className="max-w-7xl mx-auto px-6 py-20">
          <div className="flex flex-col md:flex-row md:items-end md:justify-between mb-12">
            <div>
              <p className="text-gold text-sm font-medium tracking-[0.15em] uppercase mb-2">
                Select Inventory
              </p>
              <h2 className="text-3xl font-bold text-charcoal">
                Featured Domains
              </h2>
            </div>
            <Link
              href="/portfolio"
              className="mt-4 md:mt-0 text-sm font-medium text-gold hover:text-gold-dark transition-colors"
            >
              View full portfolio &rarr;
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {featuredDomains.map((domain) => (
              <div
                key={domain.name}
                className="bg-surface border border-border rounded-lg p-6 hover:border-gold/60 hover:shadow-lg transition-all group"
              >
                <div className="flex items-start justify-between">
                  <h3 className="text-lg font-bold text-charcoal group-hover:text-charcoal transition-colors">
                    {domain.name}
                  </h3>
                  <span className="text-[10px] font-semibold tracking-wider uppercase bg-charcoal text-white px-2 py-0.5 rounded">
                    {domain.tld}
                  </span>
                </div>
                <p className="mt-1.5 text-xs text-muted uppercase tracking-wider">
                  {domain.category}
                </p>
                <p className="mt-5 text-2xl font-bold text-charcoal">
                  {domain.price}
                </p>
                <Link
                  href={`/contact?domain=${encodeURIComponent(domain.name)}`}
                  className="inline-block mt-5 text-sm font-medium text-gold hover:text-gold-dark transition-colors"
                >
                  Make an offer &rarr;
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ── */}
      <section className="bg-charcoal text-white">
        <div className="max-w-7xl mx-auto px-6 py-24 text-center">
          <p className="text-gold text-sm font-medium tracking-[0.2em] uppercase mb-4">
            Let&apos;s Talk
          </p>
          <h2 className="text-2xl md:text-3xl font-bold max-w-2xl mx-auto">
            Have a domain to sell? Need a name that&apos;s already taken?
            We handle both sides.
          </h2>
          <Link
            href="/contact"
            className="inline-block mt-10 bg-gold text-charcoal font-semibold px-8 py-3.5 rounded hover:bg-gold-light transition-colors text-sm tracking-wide"
          >
            Get in Touch
          </Link>
        </div>
      </section>
    </>
  );
}
