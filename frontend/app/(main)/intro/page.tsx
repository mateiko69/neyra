"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { markIntroSeen } from "../../../lib/introSeen";
import { IntroAiDemo } from "../../components/intro/IntroAiDemo";
import { useT } from "../../components/i18n/I18nProvider";
import { Button } from "../../components/ui";

type HeroSlide = {
  kind: "hero";
  icon: string;
  titleKey: string;
  subtitleKey: string;
};

type DemoSlide = { kind: "demo" };

type IntroSlide = HeroSlide | DemoSlide;

function slideKey(s: IntroSlide): string {
  if (s.kind === "demo") return "intro-slide-demo";
  return s.titleKey;
}

export default function IntroPage() {
  const { t } = useT("IntroPage");
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [page, setPage] = useState(0);

  const slides = useMemo<IntroSlide[]>(
    () => [
      {
        kind: "hero",
        icon: "✨",
        titleKey: "intro.slide1.title",
        subtitleKey: "intro.slide1.subtitle",
      },
      { kind: "demo" },
      {
        kind: "hero",
        icon: "💫",
        titleKey: "intro.slide2.title",
        subtitleKey: "intro.slide2.subtitle",
      },
      {
        kind: "hero",
        icon: "🛡️",
        titleKey: "intro.slide3.title",
        subtitleKey: "intro.slide3.subtitle",
      },
      {
        kind: "hero",
        icon: "👑",
        titleKey: "intro.slide4.title",
        subtitleKey: "intro.slide4.subtitle",
      },
    ],
    [],
  );

  const finish = useCallback(() => {
    markIntroSeen();
    router.replace("/login");
  }, [router]);

  const goNext = useCallback(() => {
    const last = slides.length - 1;
    if (page >= last) finish();
    else setPage((p) => Math.min(p + 1, last));
  }, [page, finish, slides.length]);

  const spring = reduceMotion
    ? { type: "tween" as const, duration: 0.2 }
    : { type: "spring" as const, stiffness: 280, damping: 34, mass: 0.85 };

  return (
    <div className="intro-page" aria-roledescription="carousel">
      <button type="button" className="intro-page__skip btn btn-ghost" onClick={finish}>
        {t("intro.skip")}
      </button>

      <div className="intro-page__viewport">
        <motion.div
          className="intro-page__track"
          style={{ width: `${slides.length * 100}%` }}
          animate={{ x: `${(-100 / slides.length) * page}%` }}
          transition={spring}
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragElastic={reduceMotion ? 0 : 0.2}
          onDragEnd={(_, { offset, velocity }) => {
            const tPx = 64;
            if (offset.x < -tPx || velocity.x < -420) {
              setPage((p) => Math.min(p + 1, slides.length - 1));
            } else if (offset.x > tPx || velocity.x > 420) {
              setPage((p) => Math.max(p - 1, 0));
            }
          }}
        >
          {slides.map((s, slideIndex) => (
            <div
              key={slideKey(s)}
              className={`intro-page__slide${s.kind === "demo" ? " intro-page__slide--demo" : ""}`}
              style={{ flex: `0 0 ${100 / slides.length}%`, width: `${100 / slides.length}%` }}
            >
              {s.kind === "hero" ? (
                <>
                  <div className="intro-page__orb" aria-hidden>
                    {s.icon}
                  </div>
                  <h1 className="intro-page__title">{t(s.titleKey)}</h1>
                  <p className="intro-page__subtitle">{t(s.subtitleKey)}</p>
                </>
              ) : (
                <IntroAiDemo isActive={page === slideIndex} reduceMotion={reduceMotion} />
              )}
            </div>
          ))}
        </motion.div>
      </div>

      <div className="intro-page__dots" role="tablist" aria-label={t("intro.dotsAria")}>
        {slides.map((s, i) => (
          <button
            key={slideKey(s)}
            type="button"
            role="tab"
            aria-selected={i === page}
            className={`intro-page__dot${i === page ? " intro-page__dot--active" : ""}`}
            onClick={() => setPage(i)}
          />
        ))}
      </div>

      <div className="intro-page__footer">
        <Button type="button" variant="primary" className="intro-page__continue" onClick={goNext}>
          {t("intro.continue")}
        </Button>
      </div>
    </div>
  );
}
