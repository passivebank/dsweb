import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — DomainSnobs",
  description:
    "Domain investment and brokerage firm specializing in high-authority expired domains and premium domain transactions since 2017.",
};

const capabilities = [
  {
    title: "Multi-Registrar Architecture",
    description:
      "Seven acquisition channels across four registrars with sub-second EPP submission capability.",
  },
  {
    title: "Proprietary Scoring",
    description:
      "40+ signal evaluation model covering traffic, authority, keywords, and comparable sales.",
  },
  {
    title: "Geographic Distribution",
    description:
      "Acquisition nodes across three data centers for competitive drop-catch timing.",
  },
];

export default function AboutPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal py-20">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight">
            About DomainSnobs
          </h1>
        </div>
      </section>

      {/* Content */}
      <section className="bg-surface py-16 md:py-24">
        <div className="max-w-3xl mx-auto px-6">
          <p className="text-slate text-base leading-relaxed mb-6">
            DomainSnobs is a domain investment and brokerage firm founded in
            2017. We specialize in acquiring high-authority expired domains and
            brokering premium domain transactions across the .com, .net, .io,
            and ccTLD markets.
          </p>

          <p className="text-slate text-base leading-relaxed mb-12">
            Our team brings deep experience in domain investment, digital media,
            SEO, and web infrastructure. We have been active in the domain
            aftermarket since 2016, building acquisition systems that identify
            undervalued domain equity before it reaches the open market.
          </p>

          <h2 className="text-2xl font-semibold text-charcoal mb-4">
            Our Approach
          </h2>

          <p className="text-slate text-base leading-relaxed mb-6">
            We believe domain equity is undervalued by the market. Our systems
            identify that gap before anyone else does.
          </p>

          <p className="text-slate text-base leading-relaxed mb-6">
            Our acquisition pipeline evaluates domains across 40+ signals
            including estimated traffic value, backlink authority profile,
            keyword commercial intent, comparable sales data, and brandability
            metrics. We operate multi-registrar infrastructure across seven
            acquisition channels with geographic distribution for competitive
            drop-catch execution.
          </p>

          <p className="text-slate text-base leading-relaxed mb-12">
            Every domain we acquire or broker is evaluated against the same
            scoring methodology. We do not speculate on trends or brandability
            alone. Our positions are backed by traffic data, link equity, and
            verifiable commercial intent.
          </p>

          <h2 className="text-2xl font-semibold text-charcoal mb-8">
            Infrastructure
          </h2>

          <div className="grid md:grid-cols-3 gap-8 mb-16">
            {capabilities.map((cap) => (
              <div
                key={cap.title}
                className="bg-background rounded-lg border border-border p-6"
              >
                <h3 className="text-base font-semibold text-charcoal mb-2">
                  {cap.title}
                </h3>
                <p className="text-sm text-muted leading-relaxed">
                  {cap.description}
                </p>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div className="text-center border-t border-border pt-12">
            <p className="text-lg text-charcoal font-medium mb-4">
              Interested in working with us?
            </p>
            <Link
              href="/contact"
              className="inline-block bg-gold text-charcoal font-medium text-sm px-8 py-3 rounded hover:opacity-90 transition-opacity"
            >
              Get in Touch
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
