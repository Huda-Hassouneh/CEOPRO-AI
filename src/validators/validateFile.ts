import * as xlsx from "xlsx";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "./../errors/error-definitions.js";
import { errorResponse } from "../types/response.js";
import { AppRequest } from "../types/request.js";
import { NextFunction, Response } from "express";

const REQUIRED_COLUMNS = ["field", "value", "date", "notes"];

export default function validateFile(
  req: AppRequest,
  res: Response,
  next: NextFunction
) {
  try {
    if (!req.file || !req.file.buffer) {
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_FILE_UPLOAD];
      return res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INVALID_FILE_UPLOAD,
            "No file buffer provided."
          )
        );
    }

    // 1. Explicit File Type Validation
    const allowedExtensions = [".csv", ".xlsx", ".xlsm"];
    const fileName = req.file.originalname.toLowerCase();
    const hasValidExtension = allowedExtensions.some((ext) =>
      fileName.endsWith(ext)
    );

    if (!hasValidExtension) {
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_FILE_UPLOAD];
      return res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INVALID_FILE_UPLOAD,
            "Invalid file type. Only .csv, .xlsx, and .xlsm files are allowed."
          )
        );
    }
    // 1. Parse the file from memory
    const workbook = xlsx.read(req.file.buffer, { type: "buffer" });
    const firstSheetName = workbook.SheetNames[0];
    const worksheet = workbook.Sheets[firstSheetName];

    // 2. Convert to a 2D array to inspect rows directly
    const rows = xlsx.utils.sheet_to_json(worksheet, { header: 1 }) as any;

    if (rows.length === 0) {
      return res
        .status(422)
        .json(
          errorResponse(
            "Unprocessable Entity",
            422,
            ERROR_CODES.INVALID_TEMPLATE,
            "The uploaded file is completely empty."
          )
        );
    }

    // 3. Dynamically locate the header row (handles Excel's top boilerplate)
    let headerRowIndex = -1;
    let headers = [];

    // Scan up to the first 10 rows to find the headers
    for (let i = 0; i < Math.min(rows.length, 10); i++) {
      const row = rows[i] || [];
      const rowStrings = row.map((cell: any) =>
        cell?.toString().toLowerCase().trim()
      );

      if (rowStrings.includes("field") && rowStrings.includes("value")) {
        headerRowIndex = i;
        headers = rowStrings;
        break;
      }
    }

    if (headerRowIndex === -1) {
      return res
        .status(422)
        .json(
          errorResponse(
            "Unprocessable Entity",
            422,
            ERROR_CODES.INVALID_TEMPLATE,
            "Invalid template format. Could not find 'Field' and 'Value' headers."
          )
        );
    }

    // 4. Validate exact column structure
    const missingColumns = REQUIRED_COLUMNS.filter(
      (col) => !headers.includes(col)
    );
    if (missingColumns.length > 0) {
      return res
        .status(422)
        .json(
          errorResponse(
            "Unprocessable Entity",
            422,
            ERROR_CODES.INVALID_TEMPLATE,
            `Missing required columns: ${missingColumns.join(", ")}.`
          )
        );
    }

    // 5. Verify the file contains actual data below the headers
    const dataRows = rows
      .slice(headerRowIndex + 1)
      .filter((row: any) => row.length > 0);
    if (dataRows.length === 0) {
      return res
        .status(422)
        .json(
          errorResponse(
            "Unprocessable Entity",
            422,
            ERROR_CODES.INVALID_TEMPLATE,
            "The file contains headers but no data records."
          )
        );
    }

    // 6. Data Type Validation (Checking the first data row as an example)
    const firstDataRow = dataRows[0];
    const dateIndex = headers.indexOf("date");
    const dateValue = firstDataRow[dateIndex];

    // Example: Ensure if a Date is provided, it can be parsed as a valid date
    if (dateValue && isNaN(Date.parse(dateValue.toString()))) {
      return res
        .status(422)
        .json(
          errorResponse(
            "Unprocessable Entity",
            422,
            ERROR_CODES.INVALID_TEMPLATE,
            `Data type error in row 1: '${dateValue}' is not a valid date format.`
          )
        );
    }

    // Passed all checks, proceed to controller
    next();
  } catch (error) {
    console.error("File Validation Middleware Error:", error);
    const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
    return res
      .status(errDef.statusCode)
      .json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INTERNAL_SERVER_ERROR,
          "Failed to parse or validate the spreadsheet."
        )
      );
  }
}
