"use client";

import { useState } from "react";
import Link from "next/link";
import { domains, categories, tlds } from "@/data/domains";

export default function PortfolioPage() {
  const [activeCategory, setActiveCategory] = useState("All");
  const [activeTld, setActiveTld] = useState("All");

  const filtered = domains.filter((d) => {
    const catMatch = activeCategory === "All" || d.category === activeCategory;
    const tldMatch = activeTld === "All" || d.tld === activeTld;
    return catMatch && tldMatch;
  });

  return (
    <>
      {/* Hero */}
      <section className="bg-charcoal text-white py-20">
        <div className="max-w-7xl mx-auto px-6">
          <h1 className="text-4xl font-bold tracking-tight">Domain Portfolio</h1>
          <p className="mt-4 text-lg text-gray-400 max-w-2xl">
            Select domains currently available for acquisition. Inquire for pricing on unlisted inventory.
          </p>
        </div>
      </section>

      {/* Filters + Grid */}
      <section className="bg-background py-16">
        <div className="max-w-7xl mx-auto px-6">
          {/* Filter Bar */}
          <div className="mb-10 space-y-4">
            {/* Category Filters */}
            <div className="flex flex-wrap gap-2">
              <span className="text-sm text-muted font-medium mr-2 self-center">Category</span>
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`text-sm px-4 py-1.5 rounded transition-colors ${
                    activeCategory === cat
                      ? "bg-gold text-charcoal font-medium"
                      : "border border-border text-muted hover:text-charcoal hover:border-charcoal"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>

            {/* TLD Filters */}
            <div className="flex flex-wrap gap-2">
              <span className="text-sm text-muted font-medium mr-2 self-center">TLD</span>
              {tlds.map((tld) => (
                <button
                  key={tld}
                  onClick={() => setActiveTld(tld)}
                  className={`text-sm px-4 py-1.5 rounded transition-colors ${
                    activeTld === tld
                      ? "bg-gold text-charcoal font-medium"
                      : "border border-border text-muted hover:text-charcoal hover:border-charcoal"
                  }`}
                >
                  {tld}
                </button>
              ))}
            </div>
          </div>

          {/* Results Count */}
          <p className="text-sm text-muted mb-6">
            {filtered.length} {filtered.length === 1 ? "domain" : "domains"} available
          </p>

          {/* Domain Grid */}
          {filtered.length === 0 ? (
            <p className="text-muted text-center py-16">
              No domains match the selected filters.
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {filtered.map((domain) => (
                <div
                  key={domain.name}
                  className="bg-surface rounded-lg border border-border p-6 shadow-sm hover:shadow-md transition-shadow"
                >
                  {/* Domain Name */}
                  <h2 className="text-xl font-bold text-charcoal leading-tight">
                    {domain.name}
                  </h2>

                  {/* Badges */}
                  <div className="flex items-center gap-2 mt-3">
                    <span className="text-xs font-medium bg-gold text-charcoal px-2.5 py-0.5 rounded-full">
                      {domain.tld}
                    </span>
                    <span className="text-xs font-medium bg-charcoal text-white px-2.5 py-0.5 rounded-full">
                      {domain.category}
                    </span>
                  </div>

                  {/* Price */}
                  <p className="text-2xl font-bold text-gold mt-5">{domain.price}</p>

                  {/* CTA */}
                  <Link
                    href={`/contact?domain=${encodeURIComponent(domain.name)}`}
                    className="inline-block mt-5 bg-gold text-charcoal text-sm font-medium px-6 py-2.5 rounded hover:opacity-90 transition-opacity"
                  >
                    Make Offer
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
