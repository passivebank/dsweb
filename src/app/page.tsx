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
    icon: "\u25CE", // ◎
    title: "Domain Acquisition",
    description:
      "Proprietary monitoring and scoring infrastructure identifies high-value domains before they hit the open market. Multi-registrar submission architecture ensures competitive capture rates.",
  },
  {
    icon: "\u2726", // ✦
    title: "Portfolio Brokerage",
    description:
      "Confidential buy-side and sell-side representation for premium domain transactions. Standard Escrow.com settlement on all brokered deals.",
  },
  {
    icon: "\u2316", // ⌖
    title: "Strategic Consulting",
    description:
      "Domain strategy advisory for brands, investors, and holding companies. Portfolio valuation, acquisition planning, and market positioning.",
  },
];

const featuredDomains = domains.filter((d) => d.featured);

export default function Home() {
  return (
    <>
      {/* ── Hero ── */}
      <section className="bg-charcoal text-white">
        <div className="max-w-7xl mx-auto px-6 py-24 md:py-32 text-center">
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight max-w-3xl mx-auto">
            Premium Domain Investments, Acquired at the Source
          </h1>
          <p className="mt-6 text-lg md:text-xl text-gray-300 max-w-2xl mx-auto leading-relaxed">
            We identify, acquire, and broker high-value domain assets for
            investors and brands.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/portfolio"
              className="bg-gold text-charcoal font-semibold px-8 py-3 rounded hover:opacity-90 transition-opacity text-sm"
            >
              Explore Portfolio
            </Link>
            <Link
              href="/contact"
              className="border border-gold text-gold font-semibold px-8 py-3 rounded hover:bg-gold hover:text-charcoal transition-colors text-sm"
            >
              Contact Us
            </Link>
          </div>
        </div>
      </section>

      {/* ── Stats Bar ── */}
      <section className="bg-surface border-b border-border">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            {stats.map((stat) => (
              <div key={stat.label}>
                <p className="text-3xl md:text-4xl font-bold text-gold">
                  {stat.value}
                </p>
                <p className="mt-2 text-sm text-muted">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Value Props ── */}
      <section className="bg-background">
        <div className="max-w-7xl mx-auto px-6 py-20">
          <div className="grid md:grid-cols-3 gap-12">
            {valueProps.map((prop) => (
              <div key={prop.title} className="text-center md:text-left">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-full border-2 border-gold text-gold text-2xl mb-6">
                  {prop.icon}
                </div>
                <h3 className="text-xl font-semibold text-charcoal">
                  {prop.title}
                </h3>
                <p className="mt-3 text-muted leading-relaxed text-sm">
                  {prop.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Featured Domains ── */}
      <section className="bg-surface">
        <div className="max-w-7xl mx-auto px-6 py-20">
          <h2 className="text-3xl font-bold text-charcoal text-center">
            Featured Domains
          </h2>
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {featuredDomains.map((domain) => (
              <div
                key={domain.name}
                className="bg-surface border border-border rounded-lg p-6 shadow-sm hover:shadow-md hover:border-gold transition-all group"
              >
                <div className="flex items-start justify-between">
                  <h3 className="text-lg font-semibold text-charcoal group-hover:text-gold-dark transition-colors">
                    {domain.name}
                  </h3>
                  <span className="text-xs font-medium bg-background text-muted px-2 py-1 rounded">
                    {domain.tld}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted">{domain.category}</p>
                <p className="mt-4 text-2xl font-bold text-charcoal">
                  {domain.price}
                </p>
                <Link
                  href={`/contact?domain=${encodeURIComponent(domain.name)}`}
                  className="inline-block mt-5 bg-gold text-charcoal text-sm font-medium px-5 py-2 rounded hover:opacity-90 transition-opacity"
                >
                  Make Offer
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ── */}
      <section className="bg-charcoal text-white">
        <div className="max-w-7xl mx-auto px-6 py-20 text-center">
          <h2 className="text-2xl md:text-3xl font-bold">
            Have a domain to sell? Looking for a specific name?
          </h2>
          <p className="mt-4 text-gray-300 text-lg">
            Get in touch with our acquisitions team.
          </p>
          <Link
            href="/contact"
            className="inline-block mt-8 bg-gold text-charcoal font-semibold px-8 py-3 rounded hover:opacity-90 transition-opacity text-sm"
          >
            Contact Us
          </Link>
        </div>
      </section>
    </>
  );
}
