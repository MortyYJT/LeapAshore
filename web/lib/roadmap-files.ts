// Which roadmap steps end in a file the applicant keeps, and what a step's row shows for files.
//
// Most steps are things to do (choose a country, book a test, pay a fee) and can only be ticked.
// A step gets a file entry only when finishing it leaves a document in the applicant's hands. That
// is stated here, step by step, keyed by the material key (`MATERIALS[...][].id` in `roadmap.ts`,
// `material_templates.key` on the server): the key is the stable join between the two, so the
// classification needs no column, no migration and no re-seed. A key that is not listed here, such
// as a step the server adds later, is tick-only until someone classifies it.

import type { Material } from "./types";

/** The steps that produce a file, each with the document it leaves behind. */
export const FILE_STEPS: Readonly<Record<string, string>> = {
  "aca-transcript": "stamped transcripts",
  "aca-enroll": "enrolment letter, or degree and graduation certificates",
  "aca-scale": "the school's grading-scale statement",
  "aca-passport": "passport photo-page scan",
  "aca-verify": "CHESICC verification report",
  "lang-score": "language score report",
  "spe-cv": "CV",
  "spe-ps": "personal statement",
  "spe-ref": "recommendation letters",
  "spe-portfolio": "portfolio",
  "spe-research": "research proposal",
  "spe-work": "employment or internship letters",
  "sub-receipt": "submission receipts",
  "dec-compare": "offer letters",
  "dec-coe": "Confirmation of Enrolment",
  "dec-visa": "visa grant, health-check and OSHC papers",
  // Typed into the visa form in the end, but drafted as a document first: it is the one kind the
  // review has criteria for (`gs-answer-length`, `gs-answer-language` in the review seed).
  "visa-gs-responses": "Genuine Student answers, drafted for review",
  "visa-gs-evidence": "Genuine Student supporting documents",
};

export function producesFile(materialKey: string): boolean {
  return Object.hasOwn(FILE_STEPS, materialKey);
}

export interface StepFiles {
  /** Whether the row offers to upload a file. */
  upload: boolean;
  /** The titles of the files already attached to the step, oldest first. */
  attached: string[];
}

/**
 * What one step's row shows for files.
 *
 * The upload is offered only on a step that produces a file. Files already attached are listed on
 * any step, including one that no longer offers the upload: they were put there before the steps
 * were classified, they still live in the library, and the row keeps saying so.
 */
export function stepFiles(materialKey: string, taskId: string | null, library: readonly Pick<Material, "title" | "taskId" | "createdAt">[]): StepFiles {
  const attached =
    taskId === null
      ? []
      : library
          .filter((material) => material.taskId === taskId)
          .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
          .map((material) => material.title);
  return { upload: producesFile(materialKey), attached };
}
