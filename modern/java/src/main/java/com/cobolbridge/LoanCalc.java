package com.cobolbridge;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Faithful Java port of legacy/LOANCALC.cbl.
 *
 * <p>Decimal arithmetic uses BigDecimal only. Every assignment applies the scale and rounding of
 * its COBOL receiving field. Each method mirrors a COBOL paragraph and cites its rule ID
 * (docs/record_layouts.md, docs/business_rules.md).
 *
 * <p>Usage: {@code java com.cobolbridge.LoanCalc <input-path> <output-path>}
 */
public final class LoanCalc {

    static final int INPUT_LEN = 28;
    static final BigDecimal TWELVE = BigDecimal.valueOf(12);
    static final BigDecimal FEE_RATE = new BigDecimal("0.05");
    static final BigDecimal MIN_FEE = new BigDecimal("5.00");
    static final BigDecimal TWO = BigDecimal.valueOf(2);

    /** One input record: LOAN-IN, 28 bytes. */
    record LoanIn(String custId, String principal, String rate, String term, String daysLate) {
        static LoanIn of(String rec) {
            return new LoanIn(rec.substring(0, 8), rec.substring(8, 17), rec.substring(17, 22),
                    rec.substring(22, 25), rec.substring(25, 28));
        }
    }

    // WORKING-STORAGE equivalents
    private BigDecimal wsInt;    // PIC 9(7)V99
    private BigDecimal wsFee;    // PIC 9(6)V99
    private BigDecimal wsDue;    // PIC 9(7)V99
    private long recCount;       // PIC 9(6)
    private long errCount;       // PIC 9(6)
    private BigDecimal dueSum = BigDecimal.ZERO.setScale(2); // PIC 9(11)V99
    private final List<String> output = new ArrayList<>();

    public static void main(String[] args) throws IOException {
        if (args.length != 2) {
            System.err.println("usage: LoanCalc <input-path> <output-path>");
            System.exit(2);
        }
        LoanCalc program = new LoanCalc();
        for (String rec : readInput(Files.readAllBytes(Path.of(args[0])))) {
            program.processRecord(LoanIn.of(rec));
        }
        program.writeTrailer();
        Files.write(Path.of(args[1]), program.render());
    }

    /**
     * READ-INPUT: GnuCOBOL LINE SEQUENTIAL framing. A short line is padded with spaces to the
     * record length. An over-long line is split, and its excess bytes are read as the next
     * record(s) (observed with GnuCOBOL 3.2).
     */
    static List<String> readInput(byte[] data) {
        String text = new String(data, StandardCharsets.ISO_8859_1);
        List<String> lines = new ArrayList<>(List.of(text.split("\n", -1)));
        if (!lines.isEmpty() && lines.get(lines.size() - 1).isEmpty()) {
            lines.remove(lines.size() - 1);
        }
        List<String> records = new ArrayList<>();
        for (String line : lines) {
            int pos = 0;
            do {
                String chunk = line.substring(pos, Math.min(line.length(), pos + INPUT_LEN));
                records.add(padRight(chunk, INPUT_LEN));
                pos += INPUT_LEN;
            } while (pos < line.length());
        }
        return records;
    }

    /** PROCESS-RECORD. */
    void processRecord(LoanIn in) {
        recCount = cobolStore(recCount + 1, 6);
        String status;
        if (validateRecord(in)) {
            calcInterest(in);
            calcLateFee(in);
            wsDue = store(wsInt.add(wsFee), 7, 2, RoundingMode.DOWN);
            dueSum = store(dueSum.add(wsDue), 11, 2, RoundingMode.DOWN); // R5
            status = "OK ";
        } else {
            wsInt = BigDecimal.ZERO;
            wsFee = BigDecimal.ZERO;
            wsDue = BigDecimal.ZERO;
            errCount = cobolStore(errCount + 1, 6);                     // R5
            status = "ERR";
        }
        output.add(in.custId() + status + digits(wsInt, 9, 2) + digits(wsFee, 8, 2) + digits(wsDue, 9, 2));
    }

    /** VALIDATE-RECORD (R4): class test NUMERIC on every numeric field, then zero checks. */
    static boolean validateRecord(LoanIn in) {
        if (!isNumeric(in.principal()) || !isNumeric(in.rate())
                || !isNumeric(in.term()) || !isNumeric(in.daysLate())) {
            return false;
        }
        return !(decimal(in.principal(), 2).signum() == 0 || decimal(in.rate(), 4).signum() == 0);
    }

    /** CALC-INTEREST (R1): COMPUTE WS-INT ROUNDED = PRINCIPAL * RATE / 12, so round half-up. */
    void calcInterest(LoanIn in) {
        BigDecimal product = decimal(in.principal(), 2).multiply(decimal(in.rate(), 4)); // exact, scale 6
        BigDecimal quotient = product.divide(TWELVE, 2, RoundingMode.HALF_UP);            // exact rounding
        wsInt = store(quotient, 7, 2, RoundingMode.HALF_UP);
    }

    /**
     * CALC-LATE-FEE (R2, R3). R2: over 15 days late, the fee is 5% of the interest, truncated
     * (COMPUTE without ROUNDED), with a minimum of 5.00. R3: over 60 days late, double the fee
     * after the minimum is applied.
     */
    void calcLateFee(LoanIn in) {
        int days = Integer.parseInt(in.daysLate());
        wsFee = BigDecimal.ZERO.setScale(2);
        if (days > 15) {
            wsFee = store(wsInt.multiply(FEE_RATE), 6, 2, RoundingMode.DOWN); // R2: truncate
            if (wsFee.compareTo(MIN_FEE) < 0) {
                wsFee = MIN_FEE;                                             // R2: minimum
            }
            if (days > 60) {
                wsFee = store(wsFee.multiply(TWO), 6, 2, RoundingMode.DOWN);  // R3: double after min
            }
        }
    }

    /** WRITE-TRAILER (R5). */
    void writeTrailer() {
        output.add("TRL" + digits(BigDecimal.valueOf(recCount), 6, 0)
                + digits(BigDecimal.valueOf(errCount), 6, 0) + digits(dueSum, 13, 2));
    }

    /** LINE SEQUENTIAL write: GnuCOBOL drops trailing spaces from each record. */
    byte[] render() {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (String rec : output) {
            bytes.writeBytes(rec.stripTrailing().getBytes(StandardCharsets.ISO_8859_1));
            bytes.write('\n');
        }
        return bytes.toByteArray();
    }

    // --- COBOL data semantics ---------------------------------------------------------------

    /** Class test NUMERIC for an unsigned DISPLAY field: every byte is a digit 0-9. */
    static boolean isNumeric(String field) {
        if (field.isEmpty()) {
            return false;
        }
        for (int i = 0; i < field.length(); i++) {
            char c = field.charAt(i);
            if (c < '0' || c > '9') {
                return false;
            }
        }
        return true;
    }

    /** Value of an unsigned implied-decimal DISPLAY field. */
    static BigDecimal decimal(String digits, int scale) {
        return new BigDecimal(new BigInteger(digits), scale);
    }

    /**
     * Store into an unsigned numeric receiving field PIC 9(intDigits)V9(scale). The value is scaled
     * with the given rounding mode (DOWN = COBOL truncation), and high-order digits that don't fit
     * are dropped, as COBOL does without ON SIZE ERROR.
     */
    static BigDecimal store(BigDecimal value, int intDigits, int scale, RoundingMode mode) {
        BigDecimal scaled = value.setScale(scale, mode);
        BigInteger modulus = BigInteger.TEN.pow(intDigits + scale);
        return new BigDecimal(scaled.unscaledValue().abs().mod(modulus), scale);
    }

    static long cobolStore(long value, int digits) {
        return value % BigInteger.TEN.pow(digits).longValueExact();
    }

    /** Format as zero-padded DISPLAY digits with implied decimals (no point, no sign). */
    static String digits(BigDecimal value, int width, int scale) {
        String s = value.setScale(scale, RoundingMode.UNNECESSARY).unscaledValue().toString();
        return "0".repeat(Math.max(0, width - s.length())) + s;
    }

    static String padRight(String s, int width) {
        return s.length() >= width ? s : s + " ".repeat(width - s.length());
    }
}
