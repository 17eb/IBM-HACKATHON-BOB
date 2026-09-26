package com.cobolbridge.naive;

import java.io.BufferedReader;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * DELIBERATE NAIVE BASELINE - do not use.
 *
 * This is the port a developer might write in an hour from the record layout alone, without
 * studying COBOL arithmetic. It exists only to measure the "before" state:
 *   - double arithmetic instead of decimal
 *   - banker's rounding (Math.rint, HALF_EVEN) for interest, where COBOL ROUNDED is half-up
 *   - the late fee is rounded, where COBOL truncates (no ROUNDED on that COMPUTE)
 * The faithful port is com.cobolbridge.LoanCalc.
 */
public class LoanCalcNaive {

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: LoanCalcNaive <input> <output>");
            System.exit(2);
        }
        int count = 0, errors = 0;
        double sum = 0;
        try (BufferedReader in = Files.newBufferedReader(Path.of(args[0]));
             PrintWriter out = new PrintWriter(Files.newBufferedWriter(Path.of(args[1])))) {
            String line;
            while ((line = in.readLine()) != null) {
                count++;
                String cust = line.length() >= 8 ? line.substring(0, 8) : String.format("%-8s", line);
                try {
                    double principal = Long.parseLong(line.substring(8, 17)) / 100.0;
                    double rate = Long.parseLong(line.substring(17, 22)) / 10000.0;
                    Integer.parseInt(line.substring(22, 25));
                    int days = Integer.parseInt(line.substring(25, 28));
                    if (principal == 0 || rate == 0) {
                        throw new IllegalArgumentException("zero principal or rate");
                    }
                    double interest = Math.rint(principal * rate / 12 * 100) / 100;
                    double fee = 0;
                    if (days > 15) {
                        fee = Math.round(interest * 0.05 * 100) / 100.0;
                        if (fee < 5.00) fee = 5.00;
                        if (days > 60) fee = fee * 2;
                    }
                    double due = interest + fee;
                    sum += due;
                    out.printf("%sOK %09d%08d%09d%n", cust,
                            Math.round(interest * 100), Math.round(fee * 100), Math.round(due * 100));
                } catch (RuntimeException e) {
                    errors++;
                    out.printf("%sERR%09d%08d%09d%n", cust, 0, 0, 0);
                }
            }
            out.printf("TRL%06d%06d%013d%n", count, errors, Math.round(sum * 100));
        }
    }
}
