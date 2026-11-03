/**
 * Request validation middleware using Zod.
 *
 * SECURITY: Validates and strips unknown fields from every request body.
 * Prevents mass assignment attacks (e.g., {"is_admin": true} in signup body).
 */

import { Request, Response, NextFunction } from "express";
import { ZodSchema, ZodError } from "zod";

export function validate(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      // .parse() validates AND strips unknown fields (safe defaults)
      req.body = schema.parse(req.body);
      next();
    } catch (err) {
      if (err instanceof ZodError) {
        return res.status(400).json({
          error: "Validation failed",
          details: err.errors.map((e) => ({
            field: e.path.join("."),
            message: e.message,
          })),
        });
      }
      return res.status(400).json({ error: "Invalid request body" });
    }
  };
}
